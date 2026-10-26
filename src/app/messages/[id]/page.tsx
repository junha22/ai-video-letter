"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { CircleCheck, Download, Eye, LoaderCircle, RefreshCw, Send, Sparkles, Video } from "lucide-react";
import { api, errorText } from "@/lib/api";
import { formatDate, formatSeconds } from "@/lib/format";
import type { Emotion, Message } from "@/lib/types";
import { useMe } from "@/lib/useMe";
import { AppShell } from "@/components/AppShell";
import { SharePanel } from "@/components/SharePanel";
import { AnchorButton, Button, Card, Notice, Spinner } from "@/components/ui";

const EDITABLE = ["draft", "ready", "failed"];
const SOURCE_LABEL = { llm: "AI가 다듬은 대본", fallback: "기본 문장 (AI 연결 안 됨)", edited: "직접 고친 대본" };
const EMOTIONS: { key: Emotion; label: string }[] = [
  { key: "neutral", label: "평온" },
  { key: "happy", label: "기쁨" },
  { key: "sad", label: "슬픔" },
  { key: "surprise", label: "놀람" },
];

function charCount(s: string) {
  return s.replace(/\s/g, "").length;
}

export default function MessagePage() {
  const { id } = useParams<{ id: string }>();
  const { me } = useMe();
  const [m, setM] = useState<Message | null>(null);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [emotion, setEmotion] = useState<Emotion>("neutral");

  const apply = useCallback((next: Message) => {
    setM(next);
    setDraft(next.script);
  }, []);

  // 다시 만들 때는 지난번에 고른 표정을 기본으로 둔다
  useEffect(() => {
    if (m?.emotion) setEmotion(m.emotion);
  }, [m?.emotion]);

  const load = useCallback(async () => {
    try {
      const next = await api<Message>(`/api/messages/${id}`);
      setM((prev) => {
        // 사용자가 고치고 있는 대본은 덮어쓰지 않는다
        if (!prev || prev.script !== next.script) setDraft(next.script);
        return next;
      });
    } catch (e) {
      setError(errorText(e));
    }
  }, [id]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (m?.status !== "generating") return;
    const t = window.setInterval(load, 1500);
    return () => window.clearInterval(t);
  }, [m?.status, load]);

  const run = async (label: string, fn: () => Promise<Message>) => {
    setBusy(label);
    setError(null);
    try {
      apply(await fn());
    } catch (e) {
      setError(errorText(e));
    }
    setBusy(null);
  };

  if (!m || !me) {
    return <AppShell back="/home">{error ? <Notice tone="error">{error}</Notice> : <Spinner />}</AppShell>;
  }

  const editable = EDITABLE.includes(m.status);
  const dirty = draft.trim() !== m.script;
  const chars = charCount(draft);

  // 후보가 여러 개인데 아직 안 골랐으면 고르는 화면만 보여 준다
  const needsChoice = editable && m.candidates.length > 1 && !m.chosen_style;

  // level을 주면 그 말투로, 안 주면 쓰던 말투 그대로 후보를 새로 만든다
  const rewrite = (level?: "반말" | "존댓말") => {
    if (dirty && !confirm("고친 내용이 사라져요. AI로 새로 쓸까요?")) return;
    run(level ? "level" : "rewrite", () =>
      api<Message>(`/api/messages/${m.id}/rewrite`, level ? { json: { speech_level: level } } : { method: "POST" }),
    );
  };
  const choose = (style: string) => {
    if (style === m.chosen_style) return;
    if (dirty && !confirm("고친 내용이 사라져요. 이 대본으로 바꿀까요?")) return;
    if (m.status === "ready" && !confirm("만들어 둔 미리보기 영상이 지워져요. 바꿀까요?")) return;
    run("choose", () => api<Message>(`/api/messages/${m.id}/choose`, { json: { style } }));
  };

  const save = () => api<Message>(`/api/messages/${m.id}`, { method: "PATCH", json: { script: draft.trim() } });
  const render = async () => {
    if (dirty) await save();
    return api<Message>(`/api/messages/${m.id}/render`, { json: { emotion } });
  };

  return (
    <AppShell back="/home" onNotification={load}>
      <div className="mb-4 flex items-center gap-2 text-sm">
        <span className="rounded-full bg-ongi-100 px-2.5 py-1 font-bold text-ongi-900">{m.template_label}</span>
        <span className="text-stone-500">{formatDate(m.created_at)}</span>
      </div>
      <p className="text-sm text-stone-500">내가 쓴 메모</p>
      <p className="mb-5 text-lg font-semibold text-stone-800">&ldquo;{m.memo}&rdquo;</p>

      {editable && m.candidates.length > 1 && (
        <CandidatePicker m={m} busy={busy} onChoose={choose} onRewrite={rewrite} />
      )}

      {error && (
        <div className="mb-4">
          <Notice tone="error">{error}</Notice>
        </div>
      )}

      {!needsChoice && (
        <div className="grid items-start gap-6 lg:grid-cols-[1.1fr_1fr]">
          {/* 대본 */}
          <Card className="min-w-0 !rounded-[28px] p-6 sm:p-8">
            <p className="mb-5 text-[10px] font-bold tracking-[0.16em] text-[#a77c65]">01 · YOUR WORDS</p>
            <div className="mb-2 flex items-center justify-between">
              <h2 className="font-bold text-stone-900">영상 대본</h2>
              <span className="text-xs font-semibold text-stone-500">{SOURCE_LABEL[m.script_source]}</span>
            </div>
            {editable ? (
              <textarea
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                rows={5}
                maxLength={400}
                className="mt-3 w-full rounded-2xl border border-[#e3e8da] bg-[#fafbf7] p-5 text-base leading-9 text-[#3e5541] outline-none focus:border-[#9bb38b] focus:ring-4 focus:ring-[#f0f4e8]"
              />
            ) : (
              <p className="rounded-2xl bg-[#FFFDF9] p-3 text-[17px] leading-relaxed">{m.script}</p>
            )}
            <p className={`mt-1 text-right text-sm ${chars > 120 ? "font-bold text-red-600" : "text-stone-500"}`}>
              {chars}자 · 약 {formatSeconds(chars / 5.5)}
            </p>
            {!dirty && m.script_warnings.length > 0 && (
              <Notice>
                {m.script_warnings.map((w) => (
                  <b key={w} className="block">
                    {w}
                  </b>
                ))}
                맞는 내용인지 확인하고, 아니면 고쳐 주세요.
              </Notice>
            )}
            {!dirty && m.script_problems.length > 0 && (
              <Notice tone="error">
                {m.script_problems.map((p) => (
                  <span key={p} className="block">
                    {p}
                  </span>
                ))}
              </Notice>
            )}
            {editable && (m.candidates.length <= 1 || dirty) && (
              <div className="mt-3 flex gap-2">
                {m.candidates.length <= 1 && (
                  <Button
                    variant="secondary"
                    className="flex-1 px-3 text-[15px]"
                    loading={busy === "rewrite"}
                    disabled={!!busy}
                    onClick={() => rewrite()}
                  >
                    <Sparkles className="h-4 w-4" /> AI로 다시 쓰기
                  </Button>
                )}
                {dirty && (
                  <Button
                    className="flex-1 px-3 text-[15px]"
                    loading={busy === "save"}
                    disabled={!!busy}
                    onClick={() => run("save", save)}
                  >
                    수정 저장
                  </Button>
                )}
              </div>
            )}
          </Card>

          {/* 영상 */}
          <div className="min-w-0 rounded-[28px] border border-[#e3e8df] bg-white p-6 shadow-[0_12px_40px_rgba(36,62,44,0.04)] sm:p-8">
            <div className="mb-5 border-b border-[#edf0e8] pb-5"><p className="text-[10px] font-bold tracking-[0.16em] text-[#a77c65]">02 · A MOMENT TOGETHER</p><h2 className="mt-2 text-lg font-semibold text-[#3e5541]">얼굴과 목소리로 전하는 편지</h2></div>
            {(m.status === "draft" || m.status === "failed") &&
              (me.can_render ? (
                <>
                  {m.status === "failed" && <Notice tone="error">{m.error ?? "영상을 만들지 못했어요."}</Notice>}
                  <EmotionPicker value={emotion} onChange={setEmotion} disabled={!!busy} />
                  <Button
                    onClick={() => run("render", render)}
                    loading={busy === "render"}
                    disabled={!!busy || (!dirty && m.script_problems.length > 0) || chars > 120}
                    className="mt-3 w-full py-4 text-lg"
                  >
                    <Video className="h-5 w-5" /> {m.status === "failed" ? "다시 만들기" : "이 대본으로 영상 만들기"}
                  </Button>
                </>
              ) : (
                <Notice>
                  목소리 등록과 얼굴 사진이 끝나야 영상을 만들 수 있어요.{" "}
                  <Link href="/home" className="font-bold underline">
                    준비 상태 보기
                  </Link>
                </Notice>
              ))}

            {m.status === "generating" && <Generating m={m} />}

            {m.video_url && ["ready", "approved", "sent", "viewed"].includes(m.status) && (
              <Card className="p-3">
                <video
                  key={m.video_url}
                  src={m.video_url}
                  poster={m.poster_url ?? undefined}
                  controls
                  playsInline
                  preload="metadata"
                  className="aspect-[4/5] max-h-[560px] w-full rounded-2xl bg-black object-contain"
                />
                <p className="mt-2 text-center text-sm text-stone-500">
                  미리보기 · {formatSeconds(m.duration ?? 0)}
                  {m.emotion && ` · 표정 ${EMOTIONS.find((e) => e.key === m.emotion)?.label ?? m.emotion}`}
                </p>
              </Card>
            )}

            {m.status === "ready" && (
              <div className="mt-4 space-y-2">
                <Notice>영상을 끝까지 확인한 뒤 승인해 주세요. 승인하면 부모님께 보낼 링크가 만들어져요.</Notice>
                <Button
                  onClick={() => run("approve", () => api<Message>(`/api/messages/${m.id}/approve`, { method: "POST" }))}
                  loading={busy === "approve"}
                  disabled={!!busy || dirty}
                  className="w-full py-4 text-lg"
                >
                  <Send className="h-5 w-5" /> 승인하고 보내기
                </Button>
                <EmotionPicker value={emotion} onChange={setEmotion} disabled={!!busy} />
                <Button
                  variant="secondary"
                  onClick={() => run("render", render)}
                  loading={busy === "render"}
                  disabled={!!busy}
                  className="w-full"
                >
                  <RefreshCw className="h-5 w-5" />{" "}
                  {dirty ? "고친 대본으로 다시 만들기" : emotion !== m.emotion ? "이 표정으로 다시 만들기" : "다시 만들기"}
                </Button>
              </div>
            )}

            {m.share && (
              <div className="mt-6">
                <Timeline m={m} />
                <div className="mt-5">
                  <SharePanel
                    message={m}
                    childName={me.parent?.child_name || me.user.name}
                    phone={me.parent?.phone}
                    onSent={apply}
                  />
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {process.env.NODE_ENV === "development" && m.video_url && <DebugDownloads m={m} />}

      {m.job && m.job.status === "done" && (
        <p className="mt-8 text-center text-xs text-stone-400">
          음성 {m.job.tts_provider} · 영상 {m.job.video_provider} · GPU {m.job.gpu_seconds}초 · $
          {m.job.cost_usd.toFixed(4)}
        </p>
      )}
    </AppShell>
  );
}

function EmotionPicker({ value, onChange, disabled }: { value: Emotion; onChange: (e: Emotion) => void; disabled: boolean }) {
  return (
    <div className="mt-3">
      <p className="mb-2 text-[11px] text-[#8a9681]">영상 속 표정</p>
      <div className="grid grid-cols-4 gap-2" role="group" aria-label="영상 속 표정">
        {EMOTIONS.map((e) => (
          <button
            key={e.key}
            type="button"
            aria-pressed={value === e.key}
            disabled={disabled}
            onClick={() => onChange(e.key)}
            className={`rounded-full border px-2 py-2 text-[15px] font-semibold disabled:opacity-60 ${
              value === e.key ? "border-[#315d4b] bg-[#315d4b] text-white" : "border-[#e5eadf] bg-[#fafbf7] text-[#809074] hover:border-[#bdcdb4]"
            }`}
          >
            {e.label}
          </button>
        ))}
      </div>
    </div>
  );
}

// 개발 모드(npm run dev)에서만 보인다. 만든 영상과 영상에 들어가기 전 TTS 음성을 그대로 내려받아 확인할 때 쓴다
function DebugDownloads({ m }: { m: Message }) {
  return (
    <Card className="mt-6 border-dashed">
      <p className="mb-3 text-sm font-bold text-stone-500">디버그 · 개발 모드에서만 보여요</p>
      <div className="flex gap-2">
        <AnchorButton variant="secondary" href={`${m.video_url}&download=1`} download className="flex-1 px-3 text-[15px]">
          <Download className="h-4 w-4" /> 영상 (mp4)
        </AnchorButton>
        {m.audio_url && (
          <AnchorButton variant="secondary" href={`${m.audio_url}&download=1`} download className="flex-1 px-3 text-[15px]">
            <Download className="h-4 w-4" /> 음성 (wav)
          </AnchorButton>
        )}
      </div>
      <p className="mt-2 text-xs text-stone-500">
        seed {m.tts_seed ?? "없음"} · {formatSeconds(m.duration ?? 0)}
      </p>
    </Card>
  );
}

function CandidatePicker({
  m,
  busy,
  onChoose,
  onRewrite,
}: {
  m: Message;
  busy: string | null;
  onChoose: (style: string) => void;
  onRewrite: (level?: "반말" | "존댓말") => void;
}) {
  const other = m.speech_level === "반말" ? "존댓말" : "반말";
  return (
    <div className="mb-6">
      <h2 className="font-bold text-stone-900">
        {m.chosen_style ? "다른 분위기로 바꿀 수도 있어요" : "마음에 드는 대본을 골라 주세요"}
      </h2>
      <p className="mb-3 mt-0.5 text-sm text-stone-500">고른 대본은 아래에서 직접 다듬을 수 있어요.</p>
      {m.speech_level && (
        <div className="mb-3 flex items-center justify-between rounded-xl bg-stone-100 px-3 py-2 text-sm">
          <span className="text-stone-700">
            <b>{m.speech_level}</b>로 썼어요
          </span>
          <button
            onClick={() => onRewrite(other)}
            disabled={!!busy}
            className="font-bold text-ongi-800 disabled:opacity-50"
          >
            {busy === "level" ? "바꾸는 중…" : `${other}로 바꾸기`}
          </button>
        </div>
      )}
      <div className="space-y-2.5">
        {m.candidates.map((c) => {
          const selected = c.style === m.chosen_style;
          return (
            <button
              key={c.style}
              onClick={() => onChoose(c.style)}
              disabled={!!busy}
              className={`w-full rounded-2xl border-2 p-4 text-left transition-colors disabled:opacity-60 ${
                selected ? "border-ongi-700 bg-ongi-50" : "border-stone-200 bg-white hover:border-stone-300"
              }`}
            >
              <div className="mb-1.5 flex items-center justify-between gap-2">
                <span
                  className={`rounded-full px-2.5 py-0.5 text-xs font-bold ${
                    selected ? "bg-ongi-700 text-white" : "bg-stone-100 text-stone-700"
                  }`}
                >
                  {c.label}
                </span>
                <span className="flex items-center gap-1 text-xs text-stone-500">
                  {selected && <CircleCheck className="h-4 w-4 text-ongi-700" />}
                  {c.char_count}자 · 약 {formatSeconds(c.est_seconds)}
                </span>
              </div>
              <p className="text-base leading-relaxed text-stone-900">{c.script}</p>
              {c.warnings.map((w) => (
                <p key={w} className="mt-1.5 text-xs font-semibold text-amber-800">
                  {w}
                </p>
              ))}
              {c.problems.map((p) => (
                <p key={p} className="mt-1.5 text-xs font-semibold text-red-700">
                  {p}
                </p>
              ))}
            </button>
          );
        })}
      </div>
      <Button
        variant="ghost"
        onClick={() => onRewrite()}
        loading={busy === "rewrite"}
        disabled={!!busy}
        className="mt-2 w-full text-[15px]"
      >
        <Sparkles className="h-4 w-4" /> 마음에 드는 게 없어요, 새로 써 주세요
      </Button>
    </div>
  );
}

function Generating({ m }: { m: Message }) {
  const stage = m.job?.status === "queued" ? "queued" : (m.job?.stage ?? "queued");
  const minutes = m.wait ? Math.ceil(m.wait.seconds / 60) : 0;
  const queuedLabel = !m.wait
    ? "순서를 기다리고 있어요"
    : m.wait.reason === "own_voice_train"
      ? `목소리를 더 닮게 다듬는 중이라 조금 늦어져요 (약 ${minutes}분)`
      : `앞선 작업이 끝나길 기다리고 있어요 (약 ${minutes}분)`;
  const steps = [
    { key: "queued", label: queuedLabel },
    { key: "tts", label: "내 목소리로 대본을 읽고 있어요" },
    { key: "video", label: "영상을 만들고 있어요" },
  ];
  const current = Math.max(
    0,
    steps.findIndex((s) => s.key === stage),
  );
  return (
    <Card>
      <p className="mb-4 text-lg font-bold">영상을 만들고 있어요</p>
      <ul className="space-y-3">
        {steps.map((s, i) => (
          <li key={s.key} className={`flex items-center gap-3 ${i > current ? "text-stone-400" : "text-stone-800"}`}>
            {i < current ? (
              <CircleCheck className="h-5 w-5 text-emerald-600" />
            ) : i === current ? (
              <LoaderCircle className="h-5 w-5 animate-spin text-ongi-700" />
            ) : (
              <span className="h-5 w-5 rounded-full border-2 border-stone-300" />
            )}
            {s.label}
          </li>
        ))}
      </ul>
      {m.job && m.job.attempts > 1 && (
        <p className="mt-4 text-sm text-amber-800">
          한 번 실패해서 다시 시도하고 있어요 ({m.job.attempts}/{m.job.max_attempts})
        </p>
      )}
      <p className="mt-4 text-sm text-stone-500">이 화면을 닫아도 계속 만들어져요.</p>
    </Card>
  );
}

function Timeline({ m }: { m: Message }) {
  const rows = [
    { label: "승인", at: m.approved_at, done: true },
    { label: "보냄", at: m.sent_at, done: !!m.sent_at || m.status === "viewed" },
    { label: `${m.parent_nickname ?? "부모님"} 시청`, at: m.viewed_at, done: !!m.viewed_at },
  ];
  return (
    <Card>
      <ol className="space-y-3">
        {rows.map((r) => (
          <li key={r.label} className="flex items-center gap-3">
            {r.done ? (
              <CircleCheck className="h-6 w-6 text-emerald-600" />
            ) : (
              <span className="h-6 w-6 rounded-full border-2 border-stone-300" />
            )}
            <span className={`flex-1 font-semibold ${r.done ? "text-stone-900" : "text-stone-400"}`}>{r.label}</span>
            <span className="text-sm text-stone-500">{r.at ? formatDate(r.at) : ""}</span>
          </li>
        ))}
      </ol>
      {m.viewed_at && (
        <p className="mt-3 flex items-center gap-1.5 text-sm font-semibold text-emerald-800">
          <Eye className="h-4 w-4" /> {m.share?.view_count}번 보셨어요
        </p>
      )}
    </Card>
  );
}
