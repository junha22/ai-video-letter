"use client";

import Link from "next/link";
import { useState } from "react";
import { ArrowUpRight, MessageCircle, Video } from "lucide-react";
import { formatConversationTime, type ConversationEvent, type ConversationMessage } from "@/lib/conversations";
import { STATUS_LABEL } from "@/lib/format";

export function ConversationEvents({ events, recipientName, childName }: { events: ConversationEvent[]; recipientName: string; childName: string }) {
  return <ol className="space-y-7" aria-label="날짜별 영상과 답글">{events.map((event) => <li key={`${event.type}-${event.id}`} id={event.type === "video" ? `video-${event.message.id}` : `reply-${event.id}`} className="scroll-mt-28">
    {event.type === "video" ? <div className="ml-auto max-w-2xl"><p className="mb-2 text-right text-xs font-semibold text-[#84917a]">{childName}의 영상 편지</p><VideoMessage message={event.message} /><p className="mt-2 text-right text-[11px] text-stone-400">{formatConversationTime(event.created_at)}</p></div> : <div className="mr-auto max-w-xl"><p className="mb-2 flex items-center gap-1.5 text-xs font-semibold text-[#9a806a]"><MessageCircle size={13} />{recipientName}의 답글</p><div className="rounded-[22px] rounded-tl-md border border-[#e7dfd2] bg-[#f5eee2] px-5 py-4"><p className="whitespace-pre-wrap break-words text-[15px] leading-8 text-[#685947]">{event.text}</p>{event.message_id !== null && <Link href={`/messages/${event.message_id}`} className="mt-3 inline-flex min-h-8 items-center gap-1 text-[11px] font-semibold text-[#998266]">답글을 남긴 영상 보기<ArrowUpRight size={12} /></Link>}</div><p className="mt-2 text-[11px] text-stone-400">{formatConversationTime(event.created_at)}</p></div>}
  </li>)}</ol>;
}

function VideoMessage({ message }: { message: ConversationMessage }) {
  const [mediaError, setMediaError] = useState(false);
  return <div className="overflow-hidden rounded-[22px] rounded-tr-md border border-[#dce5d5] bg-white shadow-[0_5px_18px_rgba(32,42,32,0.03)]">
    {message.video_url && !mediaError ? <video key={message.video_url} controls playsInline preload="metadata" poster={message.poster_url ?? undefined} onError={() => setMediaError(true)} aria-label="보낸 영상 편지" className="max-h-[420px] w-full bg-[#e9eee3] object-contain"><source src={message.video_url} type="video/mp4" />브라우저에서 영상을 재생할 수 없어요.</video> : <div className="flex min-h-32 flex-col items-center justify-center gap-3 bg-[#edf3e8] px-5 py-7 text-[#879b79]"><Video size={29} /><p className="text-xs">{mediaError ? "영상 주소가 만료되었을 수 있어요. 새로고침해 주세요." : STATUS_LABEL[message.status] ?? "영상 편지를 준비하고 있어요"}</p></div>}
    <div className="px-5 py-4"><div className="flex flex-wrap items-center justify-between gap-2"><span className="rounded-full bg-[#edf3e8] px-2.5 py-1 text-[10px] font-semibold text-[#6c885d]">{STATUS_LABEL[message.status] ?? message.status}</span><Link href={`/messages/${message.id}`} className="inline-flex min-h-9 items-center gap-1 text-xs font-semibold text-[#637d55]">편지 상세 · 공유<ArrowUpRight size={13} /></Link></div>{message.script && <details className="mt-3 text-xs text-stone-500"><summary className="min-h-8 cursor-pointer leading-8">영상 편지 내용 읽기</summary><p className="mt-2 whitespace-pre-wrap break-words text-sm leading-7 text-stone-600">{message.script}</p></details>}</div>
  </div>;
}
