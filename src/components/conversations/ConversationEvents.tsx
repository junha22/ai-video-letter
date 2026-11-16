"use client";

import Link from "next/link";
import { useState } from "react";
import { ArrowUpRight, MessageCircle, Trash2, Video } from "lucide-react";
import { formatConversationTime, type ConversationEvent, type ConversationMessage, type ConversationReplyEvent } from "@/lib/conversations";
import { STATUS_LABEL } from "@/lib/format";
import { ReplyAnalysisView } from "./ReplyAnalysis";
import { VoiceClip, formatClipLength } from "./VoiceReply";

type DeleteProps = { onDelete?: (event: ConversationEvent) => void; deleting?: string | null };
type RetryProps = { onRetryAnalysis?: (event: ConversationReplyEvent) => void; retrying?: number | null };

export function ConversationEvents({ events, recipientName, childName, onDelete, deleting, onRetryAnalysis, retrying }: { events: ConversationEvent[]; recipientName: string; childName: string } & DeleteProps & RetryProps) {
  return <ol className="space-y-7" aria-label="날짜별 영상과 답글">{events.map((event) => <li key={`${event.type}-${event.id}`} id={event.type === "video" ? `video-${event.message.id}` : `reply-${event.id}`} className="scroll-mt-28">
    {event.type === "video" ? <div className="ml-auto max-w-2xl"><p className="mb-2 text-right text-xs font-semibold text-[#81645d]">{childName}의 영상 편지</p><VideoMessage message={event.message} /><EventFooter event={event} align="right" onDelete={onDelete} deleting={deleting} /></div> : <div className="mr-auto max-w-xl"><p className="mb-2 flex items-center gap-1.5 text-xs font-semibold text-[#9a806a]"><MessageCircle size={13} />{recipientName}의 {event.kind === "voice" ? `음성 답장 · ${formatClipLength(event.audio_seconds)}` : "답글"}</p><div className="rounded-[22px] rounded-tl-md border border-[#e7dfd2] bg-[#f5eee2] px-5 py-4">{event.kind === "voice" ? <VoiceReplyBody event={event} /> : <p className="whitespace-pre-wrap break-words text-[15px] leading-8 text-[#685947]">{event.text}</p>}{event.message_id !== null && <Link href={`/messages/${event.message_id}`} className="mt-3 inline-flex min-h-8 items-center gap-1 text-[11px] font-semibold text-[#998266]">답글을 남긴 영상 보기<ArrowUpRight size={12} /></Link>}</div>{event.analysis && <ReplyAnalysisView analysis={event.analysis} retrying={retrying === event.id} onRetry={onRetryAnalysis ? () => onRetryAnalysis(event) : undefined} />}<EventFooter event={event} align="left" onDelete={onDelete} deleting={deleting} /></div>}
  </li>)}</ol>;
}

/** 음성 답장: 재생 버튼 + 자동 받아쓰기 (받아쓰기 전이거나 불확실하면 그 상태) */
function VoiceReplyBody({ event }: { event: ConversationReplyEvent }) {
  const status = event.analysis?.status;
  return <>
    {event.audio_url && <VoiceClip src={event.audio_url} seconds={event.audio_seconds} />}
    {event.text
      ? <><p className="mt-3 text-[10px] font-semibold tracking-wide text-[#a08a72]">자동 받아쓰기 · 틀린 글자가 있을 수 있어요</p><p className="mt-1 whitespace-pre-wrap break-words text-[15px] leading-8 text-[#685947]">{event.text}</p></>
      : <p className="mt-3 text-xs text-[#a08a72]">{status === "stt_uncertain" ? "말소리가 잘 들리지 않아 받아쓰지 못했어요." : status === "queued" || status === "running" ? "받아쓰는 중이에요." : "음성을 들어 보세요."}</p>}
  </>;
}

function EventFooter({ event, align, onDelete, deleting }: { event: ConversationEvent; align: "left" | "right" } & DeleteProps) {
  const key = `${event.type}-${event.id}`;
  // 만드는 중인 영상은 작업이 끝나야 지울 수 있다 (서버도 막는다)
  const canDelete = onDelete && !(event.type === "video" && event.message.status === "generating");
  return <div className={`mt-1 flex items-center gap-1 ${align === "right" ? "justify-end" : ""}`}><p className="text-[11px] text-stone-400">{formatConversationTime(event.created_at)}</p>{canDelete && <button type="button" onClick={() => onDelete?.(event)} disabled={deleting === key} aria-label={event.type === "video" ? "이 영상 편지 지우기" : "이 답글 지우기"} className="inline-flex min-h-8 items-center gap-1 rounded-lg px-2 text-[11px] font-semibold text-stone-400 hover:bg-[#f6efe9] hover:text-[#b1543d] disabled:opacity-50"><Trash2 size={12} />{deleting === key ? "지우는 중…" : "지우기"}</button>}</div>;
}

function VideoMessage({ message }: { message: ConversationMessage }) {
  const [mediaError, setMediaError] = useState(false);
  return <div className="overflow-hidden rounded-[22px] rounded-tr-md border border-[#ead9cd] bg-white shadow-[0_5px_18px_rgba(32,42,32,0.03)]">
    {message.video_url && !mediaError ? <video key={message.video_url} controls playsInline preload="metadata" poster={message.poster_url ?? undefined} onError={() => setMediaError(true)} aria-label="보낸 영상 편지" className="aspect-[4/5] max-h-[420px] w-full bg-[#fff5eb] object-contain"><source src={message.video_url} type="video/mp4" />브라우저에서 영상을 재생할 수 없어요.</video> : <div className="flex min-h-32 flex-col items-center justify-center gap-3 bg-[#fff5eb] px-5 py-7 text-[#81645d]"><Video size={29} /><p className="text-xs">{mediaError ? "영상 주소가 만료되었을 수 있어요. 새로고침해 주세요." : STATUS_LABEL[message.status] ?? "영상 편지를 준비하고 있어요"}</p></div>}
    <div className="px-5 py-4"><div className="flex flex-wrap items-center justify-between gap-2"><span className="rounded-full bg-[#fff5eb] px-2.5 py-1 text-[10px] font-semibold text-[#81645d]">{STATUS_LABEL[message.status] ?? message.status}</span><Link href={`/messages/${message.id}`} className="inline-flex min-h-9 items-center gap-1 text-xs font-semibold text-[#81645d]">편지 상세 · 공유<ArrowUpRight size={13} /></Link></div>{message.script && <details className="mt-3 text-xs text-stone-500"><summary className="min-h-8 cursor-pointer leading-8">영상 편지 내용 읽기</summary><p className="mt-2 whitespace-pre-wrap break-words text-sm leading-7 text-stone-600">{message.script}</p></details>}</div>
  </div>;
}
