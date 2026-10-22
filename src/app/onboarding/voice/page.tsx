"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { CircleAlert, CircleCheck, Mic, RotateCcw, Square } from "lucide-react";
import { api, errorText } from "@/lib/api";
import { formatSeconds } from "@/lib/format";
import { quickCheck, VoiceRecorder, type Take } from "@/lib/recorder";
import type { Sentence, VoiceState } from "@/lib/types";
import { AppShell } from "@/components/AppShell";
import { Button, Card, LinkButton, Notice, Progress, Spinner, StepHeader } from "@/components/ui";

type Phase = "intro" | "noise" | "ready" | "recording" | "checking" | "result";
type Result = { ok: boolean; problems: string[] };

const KIND_HINT: Record<Sentence["kind"], string> = {
  statement: "평소 말하듯이",
  question: "묻듯이 끝을 올려서",
  exclamation: "감정을 담아서",
};
const MAX_TAKE_SECONDS = 20;

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

  // 등록 처리 중이면 끝날 때까지 상태를 확인한다
  useEffect(() => {
    if (voice?.status !== "processing") return;
    const t = window.setInterval(load, 3000);
    return () => window.clearInterval(t);
  }, [voice?.status, load]);

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

  const current = voice?.sentences.find((s) => !s.sample?.ok && !skipped.has(s.index)) ?? null;

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
      if (e.code !== "Space" || (e.target as HTMLElement).tagName === "TEXTAREA") return;
      e.preventDefault();
      if (phase === "ready" || phase === "result") start();
      else if (phase === "recording") stop();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [phase, start, stop]);

  const skip = () => {
    if (!current) return;
    const next = new Set(skipped).add(current.index);
    // 남은 문장을 다 건너뛰었으면 처음부터 다시 돈다
    const left = voice?.sentences.filter((s) => !s.sample?.ok && !next.has(s.index)).length ?? 0;
    setSkipped(left ? next : new Set());
    setResult(null);
    setPhase("ready");
  };

  const finalize = async () => {
    setBusy(true);
    try {
      setVoice(await api<VoiceState>("/api/voice/finalize", { method: "POST" }));
      recorder.current?.close();
      recorder.current = null;
    } catch (e) {
      setError(errorText(e));
    }
    setBusy(false);
  };

  const reset = async () => {
    if (!confirm("녹음한 내용을 모두 지우고 처음부터 다시 녹음할까요?")) return;
    setVoice(await api<VoiceState>("/api/voice/reset", { method: "POST" }));
    setSkipped(new Set());
    setPhase("intro");
  };

  if (!voice) {
    return (
      <AppShell>
        <Spinner />
      </AppShell>
    );
  }

  const progress = voice.total_seconds / voice.target_seconds;
  const enough = voice.total_seconds >= voice.target_seconds;

  if (voice.status === "processing" || voice.status === "ready") {
    return (
      <AppShell back="/home">
        <StepHeader step={3} total={4} title="목소리 등록" />
        <Card className="text-center">
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
            </>
          )}
        </Card>
        <LinkButton href="/onboarding/photo" className="mt-6 w-full">
          다음: 얼굴 사진 올리기
        </LinkButton>
        {voice.status === "ready" && (
          <Button variant="ghost" onClick={reset} className="mt-2 w-full">
            처음부터 다시 녹음하기
          </Button>
        )}
      </AppShell>
    );
  }

  const meter = Math.min(1, Math.max(0, (level + 60) / 60));
  const levelHint =
    phase !== "recording" ? null : level < -45 ? "목소리가 작아요" : level > -6 ? "너무 커요, 조금 떨어져 주세요" : "좋아요";

  return (
    <AppShell back="/home">
      <StepHeader
        step={3}
        total={4}
        title="목소리를 등록해요"
        desc={`화면에 나오는 문장을 소리 내어 읽어 주세요. 모두 ${formatSeconds(voice.target_seconds)} 정도면 돼요.`}
      />

      <div className="mb-5">
        <div className="mb-2 flex justify-between text-sm font-semibold text-stone-600">
          <span>녹음한 시간</span>
          <span>
            {formatSeconds(voice.total_seconds)} / {formatSeconds(voice.target_seconds)}
          </span>
        </div>
        <Progress value={progress} />
      </div>

      {voice.status === "failed" && <Notice tone="error">{voice.error ?? "목소리 등록에 실패했어요."} 다시 등록해 주세요.</Notice>}
      {error && <Notice tone="error">{error}</Notice>}

      {phase === "intro" && (
        <Card className="mt-4">
          <ul className="list-disc space-y-2 pl-5 text-[15px] leading-relaxed text-stone-700">
            <li>TV나 음악을 끄고 조용한 곳에서 녹음해 주세요.</li>
            <li>휴대폰은 입에서 한 뼘 정도 떨어뜨려 주세요.</li>
            <li>부모님께 말하듯 평소 말투로 읽으면 더 자연스러워요.</li>
            <li>중간에 그만둬도 녹음한 문장은 저장돼요.</li>
          </ul>
          <Button onClick={openMic} className="mt-5 w-full">
            <Mic className="h-5 w-5" /> 마이크 켜기
          </Button>
        </Card>
      )}

      {phase === "noise" && (
        <Card className="mt-4 text-center">
          <Spinner />
          <p className="font-bold">주변 소리를 확인하고 있어요</p>
          <p className="mt-1 text-stone-600">잠시만 조용히 해 주세요</p>
        </Card>
      )}

      {phase !== "intro" && phase !== "noise" && current && (
        <>
          {noiseDb !== null && noiseDb > -45 && (
            <Notice>주변이 조금 시끄러워요. 조용한 곳으로 옮기면 목소리가 더 자연스럽게 만들어져요.</Notice>
          )}

          <Card className="mt-4">
            <p className="text-sm font-bold text-ongi-700">{KIND_HINT[current.kind]} 읽어 주세요</p>
            <p className="mt-3 text-[26px] font-extrabold leading-snug text-stone-900">{current.text}</p>
          </Card>

          <div className="mt-6 flex flex-col items-center">
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
                className="flex h-24 w-24 items-center justify-center rounded-full bg-ongi-800 text-white shadow-lg disabled:opacity-50"
                aria-label="녹음 시작"
              >
                <Mic className="h-10 w-10" />
              </button>
            )}
            <p className="mt-3 text-base font-bold text-stone-700">
              {phase === "recording" ? "다 읽으면 눌러 주세요" : phase === "checking" ? "확인하고 있어요…" : "눌러서 녹음 시작"}
            </p>

            <div className="mt-4 w-full">
              <div className="h-2.5 w-full overflow-hidden rounded-full bg-stone-200">
                <div
                  className={`h-full rounded-full transition-[width] duration-75 ${
                    level > -6 ? "bg-red-500" : level < -45 ? "bg-stone-400" : "bg-emerald-500"
                  }`}
                  style={{ width: `${meter * 100}%` }}
                />
              </div>
              {levelHint && <p className="mt-1 text-center text-sm font-semibold text-stone-600">{levelHint}</p>}
            </div>
          </div>

          {phase === "result" && result && (
            <div className="mt-5">
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
            <button onClick={skip} className="mx-auto mt-4 flex items-center gap-1 text-sm font-semibold text-stone-500">
              <RotateCcw className="h-4 w-4" /> 다른 문장으로 바꾸기
            </button>
          )}
        </>
      )}

      {phase !== "intro" && !current && !enough && (
        <Notice>준비된 문장을 모두 읽었어요. 처음부터 다시 녹음해 주세요.</Notice>
      )}

      {enough && (
        <Card className="mt-6 border-emerald-300 bg-emerald-50">
          <p className="font-bold text-emerald-900">충분히 녹음했어요!</p>
          <p className="mt-1 text-sm text-emerald-800">더 읽을수록 목소리가 자연스러워져요. 이제 등록해도 돼요.</p>
          <Button onClick={finalize} loading={busy} className="mt-4 w-full">
            목소리 등록하기
          </Button>
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
