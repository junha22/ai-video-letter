"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Circle, CircleAlert, CircleCheck, Mic, RotateCcw, Sparkles, Square } from "lucide-react";
import { api, errorText } from "@/lib/api";
import { formatSeconds, TUNING_LABEL, tuningNotice } from "@/lib/format";
import { quickCheck, VoiceRecorder, type Take } from "@/lib/recorder";
import type { VoiceState } from "@/lib/types";
import { AppShell } from "@/components/AppShell";
import { VoiceWorkspace } from "@/components/StudioPanels";
import { VoiceCategoryOverview, VoiceRecordingGuide, VoiceScriptLabel } from "@/components/VoiceRecordingGuide";
import { Button, Card, LinkButton, Notice, Progress, Spinner, StepHeader } from "@/components/ui";

type Phase = "intro" | "noise" | "ready" | "recording" | "checking" | "result";
type Result = { ok: boolean; problems: string[] };

const MAX_TAKE_SECONDS = 20;

/**
 * 목소리 등록은 두 단계다.
 * 1. 기본 등록(필수): 대본 한 문장을 끝까지 읽으면 등록해서 바로 기본 목소리로 영상을 만든다.
 * 2. 음색 학습(선택): 누적 target_seconds까지 녹음하면 고를 수 있다. 등록할 때 같이 고르거나, 등록 뒤 더 녹음하고 시작한다.
 *    결과가 기본 목소리 유지·실패면 더 녹음해서 다시 학습할 수 있다.
 */
export default function VoicePage() {
  const router = useRouter();
  const [voice, setVoice] = useState<VoiceState | null>(null);
  const [phase, setPhase] = useState<Phase>("intro");
  const [noiseDb, setNoiseDb] = useState<number | null>(null);
  const [level, setLevel] = useState(-100);
  const [skipped, setSkipped] = useState<Set<number>>(new Set());
  const [result, setResult] = useState<Result | null>(null);
  const [take, setTake] = useState<Take | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // 등록을 마친 뒤 음색 학습용으로 더 녹음하는 중
  const [extending, setExtending] = useState(false);
  const recorder = useRef<VoiceRecorder | null>(null);
  const stopTimer = useRef<number | null>(null);

  const load = useCallback(async () => {
    try {
      const v = await api<VoiceState>("/api/voice");
      setVoice(v);
      return v;
    } catch {
      router.replace("/");
      return null;
    }
  }, [router]);

  useEffect(() => {
    load();
    return () => recorder.current?.close();
  }, [load]);

  // 등록 처리 중이거나 음색을 다듬는 중이면 끝날 때까지 상태를 확인한다
  const tuning = voice?.tuning === "queued" || voice?.tuning === "training";
  useEffect(() => {
    if (voice?.status !== "processing" && !tuning) return;
    const t = window.setInterval(load, tuning ? 10000 : 3000);
    return () => window.clearInterval(t);
  }, [voice?.status, tuning, load]);

  // 마이크가 켜져 있는 동안 음량 막대를 갱신한다
  useEffect(() => {
    if (phase === "intro") return;
    let raf = 0;
    const tick = () => {
      if (recorder.current) setLevel(recorder.current.level());
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [phase]);

  const recordingOpen = voice?.status === "recording" || voice?.status === "failed" || (voice?.status === "ready" && extending);
  const reachedTarget = Boolean(voice && voice.total_seconds >= voice.target_seconds);
  // 처음 녹음할 때는 음색 학습 기준까지만 읽고, 등록 뒤 더 녹음할 때는 남은 문장을 계속 읽을 수 있다
  const current =
    !voice || !recordingOpen || (reachedTarget && !extending)
      ? null
      : voice.sentences.find((s) => !s.sample?.ok && !skipped.has(s.index)) ?? null;

  const closeMic = useCallback(() => {
    if (stopTimer.current) window.clearTimeout(stopTimer.current);
    recorder.current?.close();
    recorder.current = null;
    setPhase("intro");
    setResult(null);
    setTake(null);
  }, []);

  useEffect(() => {
    if (reachedTarget && !extending) closeMic();
  }, [reachedTarget, extending, closeMic]);

  const openMic = async () => {
    setError(null);
    try {
      recorder.current = await VoiceRecorder.open();
      setPhase("noise");
      setNoiseDb(await recorder.current.measureNoise());
      setPhase("ready");
    } catch (e) {
      setError(
        e instanceof DOMException && e.name === "NotAllowedError"
          ? "마이크 사용이 막혀 있어요. 주소창 옆 자물쇠 아이콘에서 마이크를 허용해 주세요."
          : errorText(e),
      );
      setPhase("intro");
    }
  };

  const stop = useCallback(async () => {
    const rec = recorder.current;
    if (!rec?.recording || !current) return;
    if (stopTimer.current) window.clearTimeout(stopTimer.current);
    setPhase("checking");
    const t = await rec.stop();
    setTake(t);
    const quick = quickCheck(t);
    if (quick.length) {
      setResult({ ok: false, problems: quick });
      setPhase("result");
      return;
    }
    try {
      const form = new FormData();
      form.append("file", t.blob, "take");
      const r = await api<Result>(`/api/voice/samples/${current.index}`, { form });
      setResult(r);
      setPhase("result");
      await load();
      if (r.ok) window.setTimeout(() => setPhase((p) => (p === "result" ? "ready" : p)), 900);
    } catch (e) {
      setResult({ ok: false, problems: [errorText(e)] });
      setPhase("result");
    }
  }, [current, load]);

  const start = useCallback(() => {
    if (!recorder.current || !current) return;
    setResult(null);
    setTake(null);
    recorder.current.start();
    setPhase("recording");
    stopTimer.current = window.setTimeout(stop, MAX_TAKE_SECONDS * 1000);
  }, [current, stop]);

  // 컴퓨터에서는 스페이스바로 녹음 시작/끝
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!current || e.code !== "Space" || (e.target as HTMLElement).tagName === "TEXTAREA") return;
      e.preventDefault();
      if (phase === "ready" || phase === "result") start();
      else if (phase === "recording") stop();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [current, phase, start, stop]);

  const skip = () => {
    if (!current) return;
    const next = new Set(skipped).add(current.index);
    // 남은 문장을 다 건너뛰었으면 처음부터 다시 돈다
    const left = voice?.sentences.filter((s) => !s.sample?.ok && !next.has(s.index)).length ?? 0;
    setSkipped(left ? next : new Set());
    setResult(null);
    setPhase("ready");
  };

  const finalize = async (tune: boolean) => {
    setBusy(true);
    setError(null);
    try {
      setVoice(await api<VoiceState>("/api/voice/finalize", { json: { tune } }));
      closeMic();
    } catch (e) {
      setError(errorText(e));
    }
    setBusy(false);
  };

  const startTuning = async () => {
    setBusy(true);
    setError(null);
    try {
      setVoice(await api<VoiceState>("/api/voice/tune", { method: "POST" }));
      setExtending(false);
      setSkipped(new Set());
      closeMic();
    } catch (e) {
      setError(errorText(e));
    }
    setBusy(false);
  };

  const recordMore = () => {
    setError(null);
    setSkipped(new Set());
    setExtending(true);
  };

  const stopRecordingMore = () => {
    setExtending(false);
    closeMic();
  };

  const reset = async () => {
    if (!confirm("녹음한 내용을 모두 지우고 처음부터 다시 녹음할까요?")) return;
    setVoice(await api<VoiceState>("/api/voice/reset", { method: "POST" }));
    setSkipped(new Set());
    setExtending(false);
    closeMic();
  };

  if (!voice) {
    return (
      <AppShell>
        <Spinner />
      </AppShell>
    );
  }

  const progress = voice.total_seconds / voice.target_seconds;
  const meter = Math.min(1, Math.max(0, (level + 60) / 60));
  const levelHint =
    phase !== "recording" ? null : level < -45 ? "목소리가 작아요" : level > -6 ? "너무 커요, 조금 떨어져 주세요" : "좋아요";
  const sentencesLeft = voice.sentences.filter((s) => !s.sample?.ok).length;

  const intro = (
    <VoiceWorkspace
      reading={<><p className="mb-4 text-xs font-semibold text-[#6b8566]">녹음 전, 잠깐만 준비해 주세요</p><h3 className="mb-5 text-2xl font-bold leading-relaxed tracking-tight text-[#344a38]">가장 편안한<br />나의 목소리로.</h3><ul className="space-y-3 text-sm leading-7 text-[#7b8574]"><li>TV나 음악을 끄고 조용한 곳에서 녹음해 주세요.</li><li>휴대폰은 입에서 한 뼘 정도 떨어뜨려 주세요.</li><li>부모님께 말하듯 평소 말투로 읽으면 더 자연스러워요.</li><li>중간에 그만둬도 녹음한 문장은 저장돼요.</li></ul></>}
      controls={<><span className="mb-5 flex h-20 w-20 items-center justify-center rounded-full border border-white/20 bg-white/10"><Mic className="h-8 w-8 text-[#e9eddb]" strokeWidth={1.5} aria-hidden="true" /></span><p className="mb-5 text-sm font-medium text-[#dae4d3]">목소리를 들려주실 준비가 됐나요?</p><Button onClick={openMic} className="w-full !bg-[#f0ecd9] !text-[#284f3e] hover:!bg-white"><Mic className="h-4 w-4" /> 마이크 켜기</Button><p className="mt-4 text-center text-[11px] leading-6 text-[#a7bda6]">편안한 목소리로, 한 문장씩 시작해요.</p></>}
    />
  );

  const noise = (
    <Card className="mt-4 py-12 text-center">
      <Spinner />
      <p className="font-bold">주변 소리를 확인하고 있어요</p>
      <p className="mt-1 text-stone-600">잠시만 조용히 해 주세요</p>
    </Card>
  );

  const recorderPanel = current && (
    <div className="mt-4 space-y-5">
      {noiseDb !== null && noiseDb > -45 && (
        <div>
          <Notice>주변이 조금 시끄러워요. 조용한 곳으로 옮기면 목소리가 더 자연스럽게 만들어져요.</Notice>
        </div>
      )}

      <VoiceWorkspace
        reading={<><VoiceScriptLabel sentence={current} /><p className="text-[25px] font-semibold leading-[1.8] tracking-tight text-[#344a38] sm:text-[30px]">{current.text}</p><p className="mt-7 text-xs leading-6 text-[#6b7767]">읽는 방법을 확인한 뒤, 대본만 소리 내어 읽어 주세요.</p></>}
        guide={<VoiceRecordingGuide sentence={current} />}
        controls={<>
          {phase === "recording" ? (
            <button
              onClick={stop}
              className="flex h-24 w-24 items-center justify-center rounded-full bg-red-600 text-white shadow-lg ring-8 ring-red-100"
              aria-label="녹음 끝내기"
            >
              <Square className="h-9 w-9 fill-white" />
            </button>
          ) : (
            <button
              onClick={start}
              disabled={phase === "checking"}
              className="flex h-24 w-24 items-center justify-center rounded-full bg-[#f0ecd9] text-[#284f3e] shadow-[0_0_0_10px_rgba(255,255,255,0.05)] disabled:opacity-50"
              aria-label="녹음 시작"
            >
              <Mic className="h-10 w-10" />
            </button>
          )}
          <p className="mt-6 text-sm font-medium text-[#e5ecdc]">
            {phase === "recording" ? "다 읽으면 눌러 주세요" : phase === "checking" ? "확인하고 있어요…" : "눌러서 녹음 시작"}
          </p>

          <div className="mt-4 w-full">
            <div className="h-1.5 w-full overflow-hidden rounded-full bg-white/15">
              <div
                className={`h-full rounded-full transition-[width] duration-75 ${
                  level > -6 ? "bg-red-500" : level < -45 ? "bg-stone-400" : "bg-emerald-500"
                }`}
                style={{ width: `${meter * 100}%` }}
              />
            </div>
            {levelHint && <p className="mt-3 text-center text-xs font-medium text-[#d5e3cd]">{levelHint}</p>}
          </div>
          <p className="mt-5 hidden text-[10px] text-[#9bb398] sm:block"><span className="mr-1.5 rounded border border-white/20 px-2 py-1 font-mono text-[9px]">SPACE</span>녹음 시작 · 끝내기</p>
        </>}
      />

      {phase === "result" && result && (
        <div className="lg:col-span-2">
          {result.ok ? (
            <Notice tone="success">
              <span className="flex items-center gap-2 font-bold">
                <CircleCheck className="h-5 w-5" /> 잘 녹음됐어요! 다음 문장으로 넘어가요.
              </span>
            </Notice>
          ) : (
            <Notice tone="error">
              <span className="mb-1 flex items-center gap-2 font-bold">
                <CircleAlert className="h-5 w-5" /> 이 문장만 다시 녹음해 주세요
              </span>
              {result.problems.map((p) => (
                <span key={p} className="block">
                  {p}
                </span>
              ))}
            </Notice>
          )}
          {take && !result.ok && <audio src={take.url} controls className="mt-3 w-full" />}
        </div>
      )}

      {phase !== "recording" && phase !== "checking" && (
        <button onClick={skip} className="mx-auto flex items-center gap-1 text-sm font-semibold text-stone-500 lg:col-span-2">
          <RotateCcw className="h-4 w-4" /> 다른 문장으로 바꾸기
        </button>
      )}
    </div>
  );

  // 마이크 켜기 → 주변 소리 확인 → 대본 읽기
  const recording = (
    <>
      {phase === "intro" && intro}
      {phase === "noise" && noise}
      {phase !== "intro" && phase !== "noise" && recorderPanel}
    </>
  );

  if (voice.status === "processing" || voice.status === "ready") {
    const notice = tuningNotice(voice.tuning, voice.tuning_report);
    // 음색 학습을 고를 수 있는 때: 아직 안 했거나, 지난 학습이 기본 목소리 유지·실패로 끝났을 때
    const tuningOpen = voice.status === "ready" && voice.tuning_available && (voice.tuning === null || notice !== null);
    const remaining = Math.max(0, voice.target_seconds - voice.total_seconds);
    return (
      <AppShell back="/home">
        <StepHeader step={3} total={4} title="목소리 등록" />
        <div className="grid items-start gap-6 lg:grid-cols-[1.35fr_1fr]">
        <Card className="py-10 text-center">
          {voice.status === "processing" ? (
            <>
              <Spinner />
              <p className="text-lg font-bold">목소리를 등록하고 있어요</p>
              <p className="mt-2 text-stone-600">끝나면 알림으로 알려 드려요. 그동안 사진을 올리고 메시지를 써 둘 수 있어요.</p>
            </>
          ) : (
            <>
              <CircleCheck className="mx-auto mb-3 h-14 w-14 text-emerald-600" />
              <p className="text-lg font-bold">목소리 등록이 끝났어요</p>
              <p className="mt-2 text-stone-600">녹음 {formatSeconds(voice.total_seconds)}</p>
              <p className="mt-1 text-sm text-stone-500">{voice.tuning ? TUNING_LABEL[voice.tuning] : "기본 목소리로 영상을 만들어요"}</p>
            </>
          )}
        </Card>
        <div className="rounded-3xl border border-[#dce9db] bg-[#edf3eb] p-6 sm:p-8">
        <p className="mb-4 text-lg font-bold text-[#315d4b]">다음으로 마음을 담을 사진을 준비해요</p>
        <LinkButton href="/onboarding/photo" className="w-full">
          다음: 얼굴 사진 올리기
        </LinkButton>
        {voice.status === "ready" && (
          <Button variant="ghost" onClick={reset} className="mt-2 w-full">
            처음부터 다시 녹음하기
          </Button>
        )}
        </div>
        </div>

        {tuningOpen && (
          <Card className="mt-6">
            <p className="flex items-center gap-2 text-lg font-bold text-[#315d4b]">
              <Sparkles className="h-5 w-5" aria-hidden="true" />
              {notice ? "다시 학습해 볼 수 있어요" : "목소리를 더 닮게 만들기 (선택)"}
            </p>
            {notice && (
              <div className="mt-3">
                <Notice>{notice} 원하면 몇 문장 더 녹음하고 다시 학습해 볼 수 있어요.</Notice>
              </div>
            )}
            <p className="mt-3 text-sm leading-7 text-stone-600">
              지금도 기본 목소리로 영상을 만들 수 있어요. 대본을 {formatSeconds(voice.target_seconds)}까지 녹음하면 내 목소리에 더 닮게 다듬는 음색 학습을 할 수 있어요.
              학습은 5분쯤 걸리고 그동안에도 영상을 만들 수 있어요. 더 닮지 않으면 기본 목소리를 그대로 써요.
            </p>
            <div className="mt-4">
              <div className="mb-2 flex justify-between text-xs text-[#788671]">
                <span>음색 학습용 녹음</span>
                <span>{formatSeconds(voice.total_seconds)} / {formatSeconds(voice.target_seconds)}</span>
              </div>
              <Progress value={progress} />
              {remaining > 0 && <p className="mt-2 text-xs text-stone-500">음색 학습까지 {formatSeconds(remaining)} 더 녹음해 주세요.</p>}
            </div>
            {error && <div className="mt-4"><Notice tone="error">{error}</Notice></div>}
            <div className="mt-4 grid gap-2 sm:grid-cols-2">
              {voice.can_tune && (
                <Button onClick={startTuning} loading={busy} className="w-full">
                  {notice ? "다시 학습하기" : "음색 학습 시작"}
                </Button>
              )}
              {extending ? (
                <Button variant="secondary" onClick={stopRecordingMore} disabled={busy} className="w-full">
                  녹음 그만하기
                </Button>
              ) : (
                sentencesLeft > 0 && (
                  <Button variant={voice.can_tune ? "secondary" : "primary"} onClick={recordMore} disabled={busy} className="w-full">
                    <Mic className="h-4 w-4" /> 더 녹음하기
                  </Button>
                )
              )}
            </div>
            {sentencesLeft === 0 && !voice.can_tune && (
              <p className="mt-3 text-sm text-stone-500">준비된 대본을 모두 읽었어요. 처음부터 다시 녹음하면 새 대본으로 녹음할 수 있어요.</p>
            )}
          </Card>
        )}

        {tuningOpen && extending && (
          <div className="mt-6">
            {recording}
            {!current && phase !== "intro" && <Notice>준비된 대본을 모두 읽었어요.</Notice>}
          </div>
        )}
      </AppShell>
    );
  }

  return (
    <AppShell back="/home">
      <StepHeader
        step={3}
        total={4}
        title="목소리를 등록해요"
        desc="대본을 한 문장씩 읽어 주세요. 한 문장만 끝까지 읽어도 기본 목소리로 등록할 수 있어요."
      />

      <div className="mb-6 rounded-2xl border border-[#e4e9dd] bg-white px-5 py-4 sm:px-6">
        <div className="mb-3 flex items-center justify-between gap-3 text-xs text-[#788671]">
          <span className="flex items-center gap-2"><Mic size={14} className="text-[#63816a]" aria-hidden="true" />나의 목소리 준비</span>
          <span>
            {formatSeconds(voice.total_seconds)} / {formatSeconds(voice.target_seconds)}
          </span>
        </div>
        <Progress value={progress} />
        <ul className="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-xs text-[#6f7c69]">
          <Milestone done={voice.basic_ready} label="기본 등록 · 대본 한 문장" />
          {voice.tuning_available && <Milestone done={reachedTarget} label={`음색 학습(선택) · ${formatSeconds(voice.target_seconds)}`} />}
        </ul>
        {voice.total_seconds > 0 && !voice.basic_ready && (
          <p className="mt-3 text-xs text-stone-500">대본 한 문장을 끝까지 읽은 녹음이 있어야 등록할 수 있어요. 조금 천천히 읽어 주세요.</p>
        )}
        {voice.basic_ready && !reachedTarget && (
          <div className="mt-4 flex flex-col gap-3 rounded-xl bg-emerald-50 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
            <p className="text-sm leading-6 text-emerald-900">
              <strong className="block">기본 목소리로 등록할 수 있어요</strong>
              지금 등록하면 바로 영상을 만들 수 있어요.
              {voice.tuning_available && ` ${formatSeconds(voice.target_seconds)}까지 더 읽으면 음색 학습도 고를 수 있어요 (선택).`}
            </p>
            <Button onClick={() => finalize(false)} loading={busy} className="shrink-0">
              기본 목소리로 등록하기
            </Button>
          </div>
        )}
      </div>

      {voice.status === "failed" && <Notice tone="error">{voice.error ?? "목소리 등록에 실패했어요."} 다시 등록해 주세요.</Notice>}
      {error && <Notice tone="error">{error}</Notice>}

      {phase === "intro" && !reachedTarget && <VoiceCategoryOverview sentences={voice.sentences} />}
      {!reachedTarget && recording}

      {phase !== "intro" && !current && !reachedTarget && (
        <Notice>
          {voice.basic_ready ? "준비된 문장을 모두 읽었어요. 기본 목소리로 등록해 주세요." : "준비된 문장을 모두 읽었어요. 처음부터 다시 녹음해 주세요."}
        </Notice>
      )}

      {reachedTarget && (
        <Card className="mt-6 border-emerald-300 bg-emerald-50">
          <p className="font-bold text-emerald-900">충분히 녹음했어요!</p>
          {voice.tuning_available ? (
            <>
              <p className="mt-1 text-sm leading-6 text-emerald-800">
                음색 학습까지 하면 목소리를 내 목소리에 더 닮게 다듬어요. 5분쯤 걸리고, 그동안에도 기본 목소리로 영상을 만들 수 있어요.
              </p>
              <Button onClick={() => finalize(true)} loading={busy} className="mt-4 w-full">
                <Sparkles className="h-4 w-4" /> 음색 학습까지 등록하기
              </Button>
              <Button variant="secondary" onClick={() => finalize(false)} disabled={busy} className="mt-2 w-full">
                기본 목소리로만 등록하기
              </Button>
            </>
          ) : (
            <>
              <p className="mt-1 text-sm text-emerald-800">이제 목소리를 등록해 주세요.</p>
              <Button onClick={() => finalize(false)} loading={busy} className="mt-4 w-full">
                목소리 등록하기
              </Button>
            </>
          )}
        </Card>
      )}

      {voice.total_seconds > 0 && (
        <Button variant="ghost" onClick={reset} className="mt-4 w-full text-sm">
          처음부터 다시 녹음하기
        </Button>
      )}
    </AppShell>
  );
}

function Milestone({ done, label }: { done: boolean; label: string }) {
  const Icon = done ? CircleCheck : Circle;
  return (
    <li className={`flex items-center gap-1.5 ${done ? "font-semibold text-emerald-700" : ""}`}>
      <Icon className="h-3.5 w-3.5" aria-hidden="true" />
      {label}
      <span className="sr-only">{done ? " 완료" : " 아직"}</span>
    </li>
  );
}
