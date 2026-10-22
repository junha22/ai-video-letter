"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { CircleCheck, Download, Eye, LoaderCircle, RefreshCw, Send, Sparkles, Video } from "lucide-react";
import { api, errorText } from "@/lib/api";
import { formatDate, formatSeconds } from "@/lib/format";
import type { Message } from "@/lib/types";
import { useMe } from "@/lib/useMe";
import { AppShell } from "@/components/AppShell";
import { SharePanel } from "@/components/SharePanel";
import { AnchorButton, Button, Card, Notice, Spinner } from "@/components/ui";

const EDITABLE = ["draft", "ready", "failed"];
const SOURCE_LABEL = { llm: "AI가 다듬은 대본", fallback: "기본 문장 (AI 연결 안 됨)", edited: "직접 고친 대본" };

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

  const apply = useCallback((next: Message) => {
    setM(next);
    setDraft(next.script);
  }, []);

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
    return (
      <AppShell back="/home">
        {error ? <Notice tone="error">{error}</Notice> : <Spinner />}
      </AppShell>
    );
  }

  const editable = EDITABLE.includes(m.status);
  const dirty = draft.trim() !== m.script;
  const chars = charCount(draft);

  const save = () => api<Message>(`/api/messages/${m.id}`, { method: "PATCH", json: { script: draft.trim() } });
  const render = async () => {
    if (dirty) await save();
    return api<Message>(`/api/messages/${m.id}/render`, { method: "POST" });
  };

  return (
    <AppShell back="/home" onNotification={load}>
      <div className="mb-4 flex items-center gap-2 text-sm">
        <span className="rounded-full bg-ongi-100 px-2.5 py-1 font-bold text-ongi-900">{m.template_label}</span>
        <span className="text-stone-500">{formatDate(m.created_at)}</span>
      </div>
      <p className="text-sm text-stone-500">내가 쓴 메모</p>
      <p className="mb-5 text-lg font-semibold text-stone-800">&ldquo;{m.memo}&rdquo;</p>

      {/* 대본 */}
      <Card>
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
            className="w-full rounded-2xl border border-stone-300 bg-[#FFFDF9] p-3 text-[17px] leading-relaxed outline-none focus:border-ongi-600"
          />
        ) : (
          <p className="rounded-2xl bg-[#FFFDF9] p-3 text-[17px] leading-relaxed">{m.script}</p>
        )}
        <p className={`mt-1 text-right text-sm ${chars > 120 ? "font-bold text-red-600" : "text-stone-500"}`}>
          {chars}자 · 약 {formatSeconds(chars / 5.5)}
        </p>
        {!dirty && m.script_problems.length > 0 && (
          <Notice tone="error">
            {m.script_problems.map((p) => (
              <span key={p} className="block">
                {p}
              </span>
            ))}
          </Notice>
        )}
        {editable && (
          <div className="mt-3 flex gap-2">
            <Button
              variant="secondary"
              className="flex-1 px-3 text-[15px]"
              loading={busy === "rewrite"}
              disabled={!!busy}
              onClick={() => {
                if (dirty && !confirm("고친 내용이 사라져요. AI로 다시 쓸까요?")) return;
                run("rewrite", () => api<Message>(`/api/messages/${m.id}/rewrite`, { method: "POST" }));
              }}
            >
              <Sparkles className="h-4 w-4" /> AI로 다시 쓰기
            </Button>
            {dirty && (
              <Button className="flex-1 px-3 text-[15px]" loading={busy === "save"} disabled={!!busy} onClick={() => run("save", save)}>
                수정 저장
              </Button>
            )}
          </div>
        )}
      </Card>

      {error && (
        <div className="mt-4">
          <Notice tone="error">{error}</Notice>
        </div>
      )}

      {/* 영상 */}
      <div className="mt-6">
        {(m.status === "draft" || m.status === "failed") &&
          (me.can_render ? (
            <>
              {m.status === "failed" && <Notice tone="error">{m.error ?? "영상을 만들지 못했어요."}</Notice>}
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
              className="aspect-[4/5] w-full rounded-2xl bg-black"
            />
            <p className="mt-2 text-center text-sm text-stone-500">미리보기 · {formatSeconds(m.duration ?? 0)}</p>
          </Card>
        )}

        {m.status === "ready" && (
          <div className="mt-4 space-y-2">
            <Notice>영상을 끝까지 확인한 뒤 승인해 주세요. 승인하면 부모님께 보낼 링크가 만들어져요.</Notice>
            <Button onClick={() => run("approve", () => api<Message>(`/api/messages/${m.id}/approve`, { method: "POST" }))} loading={busy === "approve"} disabled={!!busy || dirty} className="w-full py-4 text-lg">
              <Send className="h-5 w-5" /> 승인하고 보내기
            </Button>
            <Button variant="secondary" onClick={() => run("render", render)} loading={busy === "render"} disabled={!!busy} className="w-full">
              <RefreshCw className="h-5 w-5" /> {dirty ? "고친 대본으로 다시 만들기" : "다시 만들기"}
            </Button>
          </div>
        )}

        {m.share && (
          <div className="mt-6">
            <Timeline m={m} />
            <div className="mt-5">
              <SharePanel message={m} childName={me.user.name} phone={me.parent?.phone} onSent={apply} />
            </div>
          </div>
        )}
      </div>

      {process.env.NODE_ENV === "development" && m.video_url && <DebugDownloads m={m} />}

      {m.job && m.job.status === "done" && (
        <p className="mt-8 text-center text-xs text-stone-400">
          음성 {m.job.tts_provider} · 영상 {m.job.video_provider} · GPU {m.job.gpu_seconds}초 · ${m.job.cost_usd.toFixed(4)}
        </p>
      )}
    </AppShell>
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

function Generating({ m }: { m: Message }) {
  const stage = m.job?.status === "queued" ? "queued" : (m.job?.stage ?? "queued");
  const steps = [
    { key: "queued", label: "순서를 기다리고 있어요" },
    { key: "tts", label: "내 목소리로 대본을 읽고 있어요" },
    { key: "video", label: "영상을 만들고 있어요" },
  ];
  const current = Math.max(0, steps.findIndex((s) => s.key === stage));
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
