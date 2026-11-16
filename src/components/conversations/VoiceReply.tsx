"use client";

import { useEffect, useRef, useState } from "react";
import { Mic, Pause, Play, RotateCcw, Send, Square } from "lucide-react";
import { api, errorText } from "@/lib/api";
import { VoiceRecorder, type Take } from "@/lib/recorder";
import type { ConversationReplyEvent, VoiceReplyState } from "@/lib/conversations";

export function formatClipLength(seconds: number | null | undefined): string {
  const s = Math.max(0, Math.round(seconds ?? 0));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

/** 음성 답장 재생 버튼. big은 시니어 화면용 (큰 버튼) */
export function VoiceClip({ src, seconds, big = false, label = "음성 답장 듣기" }: { src: string; seconds?: number | null; big?: boolean; label?: string }) {
  const audio = useRef<HTMLAudioElement>(null);
  const [playing, setPlaying] = useState(false);
  const [time, setTime] = useState(0);
  const [failed, setFailed] = useState(false);
  const toggle = async () => {
    const el = audio.current;
    if (!el) return;
    if (playing) { el.pause(); return; }
    try { await el.play(); setFailed(false); } catch { setFailed(true); }
  };
  return <div className={`flex items-center gap-3 ${big ? "" : "text-sm"}`}>
    <audio ref={audio} src={src} preload="none" onPlay={() => setPlaying(true)} onPause={() => setPlaying(false)} onEnded={() => { setPlaying(false); setTime(0); }} onTimeUpdate={(e) => setTime(e.currentTarget.currentTime)} onError={() => setFailed(true)} />
    <button type="button" onClick={toggle} aria-label={playing ? "멈추기" : label} className={`flex shrink-0 items-center justify-center rounded-full bg-[#315d4b] text-white shadow-sm ${big ? "h-16 w-16" : "h-10 w-10"}`}>{playing ? <Pause size={big ? 30 : 18} /> : <Play size={big ? 30 : 18} className="ml-0.5 fill-current" />}</button>
    <span className={`font-bold tabular-nums ${big ? "text-xl" : "text-xs"} text-[#315d4b]`}>{playing || time > 0 ? `${formatClipLength(time)} / ` : ""}{formatClipLength(seconds)}</span>
    {failed && <span role="alert" className={`${big ? "text-lg" : "text-xs"} text-red-700`}>재생하지 못했어요. 다시 눌러 주세요.</span>}
  </div>;
}

type Phase = "idle" | "notice" | "starting" | "recording" | "review" | "sending";

/** 시니어 화면의 말로 답하기: 눌러서 말하기 → 다 했어요 → 다시 듣기·다시 하기·보내기. 3분이면 저절로 멈춘다 */
export function SeniorVoiceComposer({ token, state, replyTo, disabled, onSent, onNoticeAccepted }: {
  token: string;
  state: VoiceReplyState;
  replyTo: number | null;
  disabled: boolean;
  onSent: (reply: ConversationReplyEvent) => void | Promise<void>;
  onNoticeAccepted: () => void;
}) {
  const [phase, setPhase] = useState<Phase>("idle");
  const [take, setTake] = useState<Take | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const [level, setLevel] = useState(-60);
  const [error, setError] = useState("");
  const recorder = useRef<VoiceRecorder | null>(null);
  const timer = useRef<number | null>(null);
  const startedAt = useRef(0);
  const submission = useRef<{ blob: Blob; messageId: number | null; clientId: string } | null>(null);

  const stopTimer = () => { if (timer.current) window.clearInterval(timer.current); timer.current = null; };
  const close = () => { stopTimer(); recorder.current?.close(); recorder.current = null; };
  useEffect(() => () => { if (timer.current) window.clearInterval(timer.current); recorder.current?.close(); }, []);
  useEffect(() => () => { if (take) URL.revokeObjectURL(take.url); }, [take]);

  const finish = async () => {
    const rec = recorder.current;
    if (!rec?.recording) return;
    stopTimer();
    const result = await rec.stop();
    close();
    if (result.duration < 1.5) { setError("너무 짧게 녹음됐어요. 다시 한 번 말씀해 주세요."); setPhase("idle"); return; }
    if (result.speechDb < -50) setError("목소리가 작게 들려요. 다시 듣기로 확인해 보시고, 작으면 휴대폰을 입에 조금 더 가까이 대고 다시 해 주세요.");
    setTake(result);
    setPhase("review");
  };
  const finishRef = useRef(finish);
  finishRef.current = finish;

  const record = async () => {
    setError(""); setTake(null); setPhase("starting");
    try {
      recorder.current = await VoiceRecorder.open();
      recorder.current.start();
      startedAt.current = performance.now();
      setElapsed(0);
      setPhase("recording");
      timer.current = window.setInterval(() => {
        const seconds = (performance.now() - startedAt.current) / 1000;
        setElapsed(seconds);
        if (recorder.current) setLevel(recorder.current.level());
        if (seconds >= state.max_seconds) void finishRef.current();
      }, 150);
    } catch (e) {
      close();
      setPhase("idle");
      setError(e instanceof Error && e.name === "NotAllowedError" ? "마이크를 쓸 수 없어요. 휴대폰 설정에서 이 사이트의 마이크를 허용해 주세요." : errorText(e));
    }
  };

  const begin = () => {
    if (state.notice_needed) { setError(""); setPhase("notice"); return; }
    void record();
  };

  const acceptNotice = async () => {
    try {
      await api(`/api/watch/${encodeURIComponent(token)}/voice-notice`, { method: "POST" });
      onNoticeAccepted();
      await record();
    } catch (e) { setError(errorText(e)); setPhase("idle"); }
  };

  const send = async () => {
    if (!take) return;
    setPhase("sending"); setError("");
    // 시간 초과 뒤 다시 보내도 같은 답장이 두 번 저장되지 않게 같은 식별자를 쓴다
    if (!submission.current || submission.current.blob !== take.blob || submission.current.messageId !== replyTo) {
      submission.current = { blob: take.blob, messageId: replyTo, clientId: window.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}` };
    }
    const form = new FormData();
    const type = take.blob.type;
    form.append("file", take.blob, type.includes("mp4") ? "reply.m4a" : type.includes("ogg") ? "reply.ogg" : "reply.webm");
    form.append("client_id", submission.current.clientId);
    if (replyTo !== null) form.append("message_id", String(replyTo));
    try {
      const reply = await api<ConversationReplyEvent>(`/api/watch/${encodeURIComponent(token)}/voice-replies`, { form });
      submission.current = null;
      setTake(null);
      setPhase("idle");
      await onSent(reply);
    } catch (e) { setError(errorText(e)); setPhase("review"); }
  };

  const bar = Math.max(4, Math.min(100, ((level + 60) / 50) * 100));
  return <div className="mt-4">
    {phase === "idle" || phase === "starting" ? <button type="button" onClick={begin} disabled={disabled || phase === "starting"} className="flex min-h-20 w-full items-center justify-center gap-3 rounded-[22px] bg-[#315d4b] px-5 py-4 text-2xl font-extrabold text-white shadow-sm disabled:opacity-50"><Mic size={30} />{phase === "starting" ? "마이크를 켜고 있어요" : "말로 답하기"}</button> : null}
    {phase === "notice" && state.notice && <div className="rounded-[22px] border-2 border-[#cbd9ce] bg-[#f4f8f1] p-5">
      <p className="text-xl font-bold leading-9">{state.notice}</p>
      <div className="mt-4 grid gap-3 sm:grid-cols-2"><button type="button" onClick={acceptNotice} className="min-h-16 rounded-2xl bg-[#315d4b] px-4 text-xl font-bold text-white">알겠어요, 말로 답할게요</button><button type="button" onClick={() => setPhase("idle")} className="min-h-16 rounded-2xl border-2 border-[#cbd9ce] bg-white px-4 text-xl font-bold text-[#315d4b]">그만두기</button></div>
    </div>}
    {phase === "recording" && <div className="rounded-[22px] border-2 border-[#e7b9ad] bg-[#fff4f0] p-5 text-center">
      <p className="text-xl font-bold text-[#a8321e]">듣고 있어요. 편하게 말씀해 주세요.</p>
      <p className="mt-2 text-3xl font-extrabold tabular-nums">{formatClipLength(elapsed)} <span className="text-lg font-bold text-stone-500">/ {formatClipLength(state.max_seconds)}</span></p>
      <div className="mx-auto mt-4 h-4 w-full max-w-sm overflow-hidden rounded-full bg-white" aria-hidden="true"><div className="h-full rounded-full bg-[#e0735b] transition-[width]" style={{ width: `${bar}%` }} /></div>
      <button type="button" onClick={() => { void finish(); }} className="mt-5 flex min-h-20 w-full items-center justify-center gap-3 rounded-[22px] bg-[#a8321e] text-2xl font-extrabold text-white"><Square size={26} className="fill-current" />다 했어요</button>
    </div>}
    {(phase === "review" || phase === "sending") && take && <div className="rounded-[22px] border-2 border-[#cbd9ce] bg-white p-5">
      <p className="mb-3 text-xl font-bold">녹음한 목소리를 들어 보세요</p>
      <VoiceClip src={take.url} seconds={take.duration} big label="녹음 다시 듣기" />
      <div className="mt-5 grid gap-3 sm:grid-cols-2">
        <button type="button" onClick={() => { void record(); }} disabled={phase === "sending"} className="flex min-h-16 items-center justify-center gap-2 rounded-2xl border-2 border-[#cbd9ce] px-4 text-xl font-bold text-[#315d4b] disabled:opacity-50"><RotateCcw size={24} />다시 하기</button>
        <button type="button" onClick={() => { void send(); }} disabled={phase === "sending"} className="flex min-h-16 items-center justify-center gap-2 rounded-2xl bg-[#315d4b] px-4 text-xl font-bold text-white disabled:opacity-60"><Send size={24} />{phase === "sending" ? "보내고 있어요" : "보내기"}</button>
      </div>
    </div>}
    {error && <p role="alert" className="mt-3 text-lg font-bold leading-8 text-red-700">{error}</p>}
  </div>;
}
