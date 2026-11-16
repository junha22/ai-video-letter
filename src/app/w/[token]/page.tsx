"use client";

import { useEffect, useRef, useState } from "react";
import { useParams } from "next/navigation";
import { ArrowDown, CalendarDays, Heart, Play, RotateCcw, Send, X } from "lucide-react";
import { api, ApiError, errorText } from "@/lib/api";
import { Button, Notice, Spinner } from "@/components/ui";
import { ChatCalendar } from "@/components/conversations/ChatCalendar";
import { SeniorVoiceComposer, VoiceClip, formatClipLength } from "@/components/conversations/VoiceReply";
import { formatConversationDate, formatConversationTime } from "@/lib/conversations";
import type { ConversationReplyEvent, ConversationVideoEvent, PublicConversationFeed, VoiceReplyState } from "@/lib/conversations";
import { byDay, eventKey, useChatFeed } from "@/lib/useChatFeed";

const gone = (e: unknown) => e instanceof ApiError && [404, 410].includes(e.status);
const shortDate = (date: string) => `${Number(date.slice(5, 7))}월 ${Number(date.slice(8))}일`;

/** 링크 하나로 그 대상자의 대화방 전체를 본다. 사용자 대화방처럼 날짜가 이어지는 채팅이고, 새로 승인된 영상도 이어 붙는다 */
export default function WatchPage() {
  const { token } = useParams<{ token: string }>();
  const [childName, setChildName] = useState("");
  const [blocked, setBlocked] = useState(false);
  const [calendarOpen, setCalendarOpen] = useState(false);
  const [text, setText] = useState("");
  const [replyTo, setReplyTo] = useState<{ id: number; date: string } | null>(null);
  const [sending, setSending] = useState(false);
  const [notice, setNotice] = useState("");
  // 답장 살펴보기가 켜진 대화방에만 '말로 답하기'가 보인다 (서버가 voice_reply를 보낼 때만)
  const [voice, setVoice] = useState<VoiceReplyState | null>(null);
  const mounted = useRef(true);
  const sendingRef = useRef(false);
  const roomRef = useRef(token);
  roomRef.current = token;
  const submission = useRef<{ text: string; messageId: number | null; clientId: string } | null>(null);
  const composer = useRef<HTMLTextAreaElement>(null);

  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);

  const feed = useChatFeed<PublicConversationFeed>({
    room: token,
    // 링크가 막히면(취소·만료) 더 묻지 않는다
    enabled: !blocked,
    refreshMs: 8000,
    autoLoadOlder: true,
    fetchFeed: (query) => api<PublicConversationFeed>(`/api/watch/${encodeURIComponent(token)}/feed${query}`),
    onPage: (res) => { setChildName(res.child_name); setVoice(res.voice_reply?.available ? res.voice_reply : null); },
    onError: (e) => { if (gone(e)) setBlocked(true); },
  });
  const { chat, days, today, focusDate, loading } = feed;

  const sendReply = async () => {
    const value = text.trim();
    if (!value || sendingRef.current || blocked) return;
    sendingRef.current = true; setSending(true); feed.setError(null); setNotice("");
    const messageId = replyTo?.id ?? null;
    // A retry after a timeout reuses the key, preventing duplicate saved replies.
    if (!submission.current || submission.current.text !== value || submission.current.messageId !== messageId) {
      submission.current = { text: value, messageId, clientId: window.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}` };
    }
    try {
      const reply = await api<ConversationReplyEvent>(`/api/watch/${encodeURIComponent(token)}/replies`, { json: { text: value, client_id: submission.current.clientId, message_id: messageId } });
      if (!mounted.current || roomRef.current !== token) return;
      setText(""); submission.current = null;
      showSent(reply, "답글을 보냈어요. 보낸 분이 확인할 수 있어요.");
    } catch (e) {
      if (!mounted.current) return;
      feed.setError(errorText(e));
      if (gone(e)) setBlocked(true);
    } finally {
      sendingRef.current = false;
      if (mounted.current) setSending(false);
    }
  };

  const showSent = (reply: ConversationReplyEvent, message: string) => {
    if (!mounted.current || roomRef.current !== token) return;
    setReplyTo(null);
    // 보낸 답글을 바로 맨 아래에 붙인다 (지난 날짜를 보고 있었다면 최근 대화로 돌아간다)
    feed.addEvents([reply]);
    setNotice(message);
    void feed.refresh();
  };
  const noticeAccepted = () => setVoice((old) => old && { ...old, notice_needed: false });
  const acceptNotice = async () => {
    try {
      await api(`/api/watch/${encodeURIComponent(token)}/voice-notice`, { method: "POST" });
      noticeAccepted();
    } catch (e) {
      feed.setError(errorText(e));
      if (gone(e)) setBlocked(true);
    }
  };

  if (blocked) return <main className="mx-auto min-h-screen max-w-xl bg-[#fff8ef] px-5 pb-12 pt-7 text-stone-900 sm:px-8"><h1 className="text-3xl font-extrabold">대화방에 들어갈 수 없어요</h1><p role="alert" className="mt-5 text-xl leading-9">{feed.error}<br />보낸 분께 새 영상 편지 링크를 부탁해 주세요.</p></main>;

  const loadedVideos = new Set(chat?.events.filter((event) => event.type === "video").map((event) => event.id) ?? []);
  const startReply = (event: ConversationVideoEvent) => {
    if (sending) return;
    setReplyTo({ id: event.id, date: event.date });
    setNotice("");
    composer.current?.focus();
  };
  const openVideo = (id: number) => document.getElementById(`senior-video-${id}`)?.scrollIntoView({ behavior: "smooth", block: "start" });

  return <main className="mx-auto flex h-[100dvh] max-w-xl flex-col bg-[#fff8ef] text-stone-900">
    <header className="relative shrink-0 border-b border-[#e6e3d7] px-4 pb-3 pt-4 sm:px-6">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="flex items-center gap-1.5 text-base font-bold text-[#c8493c]"><Heart size={19} /> 온기 · 영상 편지</p>
          <h1 className="mt-1 break-keep text-[24px] font-extrabold leading-snug">{childName ? `${childName}님과 나누는 이야기` : "우리의 대화방"}</h1>
        </div>
        <button type="button" onClick={() => setCalendarOpen((open) => !open)} aria-expanded={calendarOpen} aria-controls="senior-calendar" className={`flex min-h-16 shrink-0 flex-col items-center justify-center gap-0.5 rounded-2xl border-2 px-3 text-sm font-bold ${calendarOpen ? "border-[#c8493c] bg-[#c8493c] text-white" : "border-[#ead9cd] bg-white text-[#c8493c]"}`}>{calendarOpen ? <X size={24} /> : <CalendarDays size={24} />}{calendarOpen ? "닫기" : "날짜로 찾기"}</button>
      </div>
      <p className="mt-2 text-sm leading-6 text-stone-500">보낸 분이 승인한 말을 AI 목소리와 얼굴로 만든 영상이에요. 답글은 보낸 분께 전달되고 월간 대화 기록에 쓰여요.{voice ? " 이 대화방에서는 답글(음성은 받아쓴 글)을 네이버 클로바 AI로 정리해 보낸 분께만 보여 드려요. 음성 파일은 보내지 않아요. 진단이 아니에요." : ""}</p>
      {calendarOpen && <div id="senior-calendar" className="absolute inset-x-3 top-full z-30 mt-2 rounded-3xl bg-white p-2 shadow-2xl ring-1 ring-[#ead9cd]">
        <p className="px-2 pb-2 pt-1 text-lg font-bold text-[#c8493c]">대화한 날을 눌러 주세요</p>
        <ChatCalendar large activeDays={days.map((day) => day.date)} selected={focusDate} today={today} onSelect={(date) => { setCalendarOpen(false); void feed.jumpTo(date); }} />
      </div>}
    </header>

    {feed.error && <div role="alert" className="shrink-0 px-4 pt-3 sm:px-6"><Notice tone="error"><span className="text-base">{feed.error}</span> <button type="button" className="min-h-12 px-2 text-base font-bold underline" onClick={feed.retry}>다시 불러오기</button></Notice></div>}

    <div className="relative min-h-0 flex-1">
      <div ref={feed.scroller} onScroll={feed.onScroll} aria-busy={loading} aria-label="영상과 답글" className="h-full overflow-y-auto overscroll-contain px-4 pb-6 [overflow-anchor:none] sm:px-6">
        <div ref={feed.content}>
          {!chat ? (loading ? <div className="py-20"><Spinner label="대화를 불러오고 있어요" /></div> : null)
            : chat.events.length === 0 ? <div className="mt-8 rounded-3xl border border-dashed border-[#ead9cd] bg-white px-5 py-9 text-center"><p className="text-xl leading-9">아직 영상 편지가 없어요.<br />먼저 안부를 남겨 보세요.</p></div>
              : <>
                {chat.hasOlder
                  ? <div className="pt-5"><Button variant="secondary" loading={feed.loadingOlder} onClick={() => { void feed.loadOlder(); }} className="w-full !text-lg">이전 대화 보기</Button></div>
                  : <p className="pt-6 text-center text-base text-stone-500">{childName ? `${childName}님과 나눈 첫 대화예요` : "첫 대화예요"}</p>}
                {byDay(chat.events).map(([day, items]) => <section key={day} data-day={day} aria-label={formatConversationDate(day)}>
                  <div className="sticky top-0 z-10 flex justify-center py-3"><span className={`rounded-full px-4 py-1.5 text-base font-bold shadow-sm ring-1 ${focusDate === day ? "bg-[#c8493c] text-white ring-[#c8493c]" : "bg-white/95 text-[#5f6f57] ring-[#ead9cd]"}`}>{formatConversationDate(day)}{day === today ? " · 오늘" : ""}</span></div>
                  <ol className="space-y-6">{items.map((event) => <li key={eventKey(event)}>
                    {event.type === "video"
                      ? <SeniorVideo event={event} token={token} childName={childName} replying={replyTo?.id === event.id} onReply={() => startReply(event)} />
                      : <SeniorReply event={event} onOpenVideo={event.message_id !== null && loadedVideos.has(event.message_id) ? () => openVideo(event.message_id!) : undefined} />}
                  </li>)}</ol>
                </section>)}
                {chat.hasNewer && <div className="flex flex-col gap-3 pt-7"><Button variant="secondary" loading={feed.loadingNewer} onClick={() => { void feed.loadNewer(); }} className="w-full !text-lg">이후 대화 보기</Button><Button onClick={feed.showLatest} className="w-full !text-lg">최근 대화로</Button></div>}
              </>}
        </div>
      </div>
      {chat && feed.awayFromBottom && <button type="button" onClick={feed.showLatest} className="absolute bottom-4 left-1/2 z-20 flex min-h-14 -translate-x-1/2 items-center gap-2 whitespace-nowrap rounded-full bg-[#c8493c] px-5 text-lg font-bold text-white shadow-lg"><ArrowDown size={22} />{feed.unseen ? "새 소식이 왔어요" : "최근 대화로"}</button>}
    </div>

    <footer className="shrink-0 border-t border-[#e6e3d7] bg-white px-4 pb-[max(12px,env(safe-area-inset-bottom))] pt-3 sm:px-6">
      {replyTo && <div className="mb-2 flex items-center justify-between gap-2 rounded-xl bg-[#fff0bd] px-3 py-1.5 text-base"><span className="min-w-0">{replyTo.date === today ? "오늘" : shortDate(replyTo.date)} 영상에 답글을 쓰고 있어요{replyTo.date !== today ? ". 답글은 오늘 대화에 이어져요" : ""}</span><button type="button" disabled={sending} onClick={() => setReplyTo(null)} className="flex min-h-12 shrink-0 items-center gap-1 px-2 font-bold underline"><X size={18} />취소</button></div>}
      {voice && <div className="mb-3">
        {voice.notice_needed && voice.notice && <div className="mb-2 rounded-2xl bg-[#f4f8f1] p-3"><p className="text-base leading-7">{voice.notice}</p><button type="button" onClick={() => { void acceptNotice(); }} className="mt-2 min-h-12 w-full rounded-2xl border-2 border-[#ead9cd] bg-white px-4 text-lg font-bold text-[#c8493c]">알겠어요</button></div>}
        <SeniorVoiceComposer token={token} state={voice} replyTo={replyTo?.id ?? null} disabled={sending || !chat} onNoticeAccepted={noticeAccepted} onSent={(reply) => showSent(reply, "음성 답장을 보냈어요. 보낸 분이 들어 볼 수 있어요.")} />
        <p className="mt-2 text-center text-base font-bold text-stone-500">또는 글로 쓰기</p>
      </div>}
      <div className="flex items-end gap-2">
        <label htmlFor="senior-reply" className="sr-only">보낼 답글</label>
        <textarea id="senior-reply" ref={composer} value={text} disabled={sending} onChange={(e) => { setText(e.target.value); if (notice) setNotice(""); }} maxLength={1000} rows={2} placeholder="예: 영상 잘 봤다. 오늘은 산책도 다녀왔어." className="max-h-40 min-h-[64px] min-w-0 flex-1 resize-none rounded-2xl border-2 border-[#ead9cd] bg-[#fff5eb] px-4 py-3 text-[20px] leading-8 outline-none focus:border-[#c8493c]" />
        <Button onClick={sendReply} loading={sending} disabled={!text.trim() || !chat} className="min-h-16 shrink-0 !px-4 !text-lg"><Send size={22} />{sending ? "보내는 중" : "보내기"}</Button>
      </div>
      <p role="status" aria-live="polite" className="mt-1 min-h-6 text-base font-bold text-[#c8493c]">{notice || (text.length > 900 ? `${text.length} / 1,000자` : "")}</p>
    </footer>
  </main>;
}

function SeniorReply({ event, onOpenVideo }: { event: ConversationReplyEvent; onOpenVideo?: () => void }) {
  const voice = event.kind === "voice";
  return <div className="ml-auto max-w-[85%]">
    <div className="rounded-[24px] rounded-br-md border border-[#ead9cd] bg-[#fff5eb] px-5 py-4">
      {event.message_id !== null && (onOpenVideo
        ? <button type="button" onClick={onOpenVideo} className="mb-1 min-h-10 text-left text-base font-bold text-[#c8493c] underline">영상에 남긴 답글 · 영상 보기</button>
        : <p className="mb-1 text-base font-bold text-[#c8493c]">영상에 남긴 답글</p>)}
      {/* 음성 답장은 재생만 보여 준다 (받아쓰기·분석은 시니어 화면에 보이지 않는다) */}
      {voice && event.audio_url
        ? <VoiceClip src={event.audio_url} seconds={event.audio_seconds} big label="내 음성 답장 듣기" />
        : <p className="whitespace-pre-wrap break-words text-[21px] leading-9 [overflow-wrap:anywhere]">{event.text}</p>}
    </div>
    <time dateTime={event.created_at} className="mt-1 block text-right text-sm text-stone-500">{voice ? `내가 남긴 음성 답장 · ${formatClipLength(event.audio_seconds)}` : "내가 남긴 답글"} · {formatConversationTime(event.created_at)}</time>
  </div>;
}

function SeniorVideo({ event, token, childName, replying, onReply }: { event: ConversationVideoEvent; token: string; childName: string; replying: boolean; onReply: () => void }) {
  const video = useRef<HTMLVideoElement>(null);
  const reported = useRef(false);
  const [started, setStarted] = useState(false);
  const [ended, setEnded] = useState(false);
  const [time, setTime] = useState(0);
  const [error, setError] = useState("");
  const m = event.message;
  const play = async () => {
    if (!video.current) return;
    if (ended) video.current.currentTime = 0;
    try { await video.current.play(); setStarted(true); setEnded(false); setError(""); }
    catch { setError("재생하지 못했어요. 다시 눌러 주세요."); }
  };
  const viewed = () => {
    setStarted(true);
    if (reported.current) return;
    reported.current = true;
    api(`/api/watch/${encodeURIComponent(token)}/messages/${m.id}/viewed`, { method: "POST" }).catch(() => { reported.current = false; });
  };
  const caption = m.captions?.find((c) => time >= c.start && time < c.end)?.text;
  return <article id={`senior-video-${m.id}`} className="mr-auto max-w-[94%] scroll-mt-16">
    <p className="mb-2 text-lg font-bold text-[#c8493c]">{childName ? `${childName}님이 보낸 영상 편지` : "영상 편지"}</p>
    <div className={`overflow-hidden rounded-[26px] rounded-tl-md border bg-white p-3 shadow-sm sm:p-4 ${replying ? "border-[#c8493c] ring-2 ring-[#c8493c]" : "border-[#ead9cd]"}`}>
      <div className="relative aspect-[4/5] overflow-hidden rounded-2xl bg-black"><video ref={video} src={m.video_url || undefined} poster={m.poster_url || undefined} controls={started} playsInline preload="metadata" onPlay={viewed} onEnded={() => setEnded(true)} onTimeUpdate={(e) => setTime(e.currentTarget.currentTime)} onError={() => setError("영상을 불러오지 못했어요. 링크 기간이 지났다면 보낸 분께 새 링크를 부탁해 주세요.")} className="h-full w-full object-contain" />{(!started || ended) && <button type="button" onClick={play} className="absolute inset-0 flex flex-col items-center justify-center gap-4 bg-black/25" aria-label={ended ? "영상 다시 보기" : "영상 재생"}><span className="flex h-24 w-24 items-center justify-center rounded-full bg-[#ffe17f] text-stone-900 shadow-xl">{ended ? <RotateCcw size={42} /> : <Play size={44} className="ml-1 fill-current" />}</span><span className="rounded-full bg-black/70 px-5 py-3 text-xl font-bold text-white">{ended ? "다시 보기" : "눌러서 보기"}</span></button>}</div>
      {caption && <p className="mt-4 text-center text-2xl font-bold leading-9">{caption}</p>}
      {error && <p role="alert" className="mt-3 text-lg leading-8 text-red-700">{error}</p>}
      <p className="mt-4 whitespace-pre-wrap break-words px-1 text-xl leading-9">{m.script}</p>
      <button type="button" onClick={onReply} aria-pressed={replying} className={`mt-4 min-h-14 w-full rounded-2xl border-2 px-4 py-3 text-lg font-bold ${replying ? "border-[#c8493c] bg-[#c8493c] text-white" : "border-[#ead9cd] text-[#c8493c]"}`}>{replying ? "이 영상에 답글을 쓰고 있어요" : "이 영상에 답글 남기기"}</button>
    </div>
    <time dateTime={event.created_at} className="mt-1 block text-sm text-stone-500">{formatConversationTime(event.created_at)}</time>
  </article>;
}
