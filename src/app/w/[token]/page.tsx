"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useParams } from "next/navigation";
import { Heart, Play, RotateCcw, Send } from "lucide-react";
import { api, ApiError, errorText } from "@/lib/api";
import { Button, Notice, Spinner } from "@/components/ui";
import { formatConversationDate, formatConversationTime, kstDate, mergeConversationEvents } from "@/lib/conversations";
import type { ConversationReplyEvent, ConversationVideoEvent, PublicConversationThread } from "@/lib/conversations";

/** A bearer link opens one recipient's room, including new approved letters. */
export default function WatchPage() {
  const { token } = useParams<{ token: string }>();
  const [thread, setThread] = useState<PublicConversationThread | null>(null);
  const [selectedDate, setSelectedDate] = useState("");
  const [today, setToday] = useState(kstDate);
  const [error, setError] = useState<string | null>(null);
  const [blocked, setBlocked] = useState(false);
  const [loading, setLoading] = useState(false);
  const [text, setText] = useState("");
  const [replyTo, setReplyTo] = useState<number | null>(null);
  const [sending, setSending] = useState(false);
  const [notice, setNotice] = useState("");
  const requestVersion = useRef(0);
  const mounted = useRef(true);
  const sendingRef = useRef(false);
  const pagingRef = useRef(false);
  const roomRef = useRef(token);
  roomRef.current = token;
  const submission = useRef<{ text: string; messageId: number | null; clientId: string } | null>(null);
  const composer = useRef<HTMLTextAreaElement>(null);
  const invalidateRequests = useCallback(() => { requestVersion.current += 1; }, []);

  useEffect(() => { mounted.current = true; return () => { mounted.current = false; invalidateRequests(); }; }, [invalidateRequests]);

  const handleError = useCallback((e: unknown) => {
    if (!mounted.current) return;
    setError(errorText(e));
    if (e instanceof ApiError && [404, 410].includes(e.status)) { setBlocked(true); setThread(null); }
  }, []);

  const load = useCallback(async (quiet = false) => {
    if (quiet && pagingRef.current) return;
    const version = ++requestVersion.current;
    if (!quiet) setLoading(true);
    try {
      const data = await api<PublicConversationThread>(`/api/watch/${encodeURIComponent(token)}/conversation${selectedDate ? `?date=${selectedDate}` : ""}`);
      if (!mounted.current || version !== requestVersion.current) return;
      setThread((old) => {
        if (!old || old.selected_date !== data.selected_date) return data;
        const preserveCursor = old.events.length > data.events.length;
        return { ...data, events: mergeConversationEvents(old.events, data.events), ...(preserveCursor ? { has_more: old.has_more, next_before: old.next_before } : {}) };
      });
      setToday(data.today); setError(null); setBlocked(false);
    } catch (e) { if (version === requestVersion.current) handleError(e); }
    finally { if (mounted.current && version === requestVersion.current) setLoading(false); }
  }, [token, selectedDate, handleError]);

  useEffect(() => {
    load();
    const timer = window.setInterval(() => load(true), 8000);
    const focus = () => load(true);
    window.addEventListener("focus", focus);
    return () => { invalidateRequests(); window.clearInterval(timer); window.removeEventListener("focus", focus); };
  }, [load, invalidateRequests]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      const next = kstDate();
      if (next === today) return;
      setToday(next);
      if (!selectedDate || selectedDate === today) { setSelectedDate(""); setThread(null); setReplyTo(null); load(true); }
    }, 1000);
    return () => window.clearInterval(timer);
  }, [today, selectedDate, load]);

  const selectDay = (date: string) => {
    requestVersion.current++;
    setSelectedDate(date === today ? "" : date); setThread(null); setReplyTo(null); setNotice(""); setError(null);
  };

  const older = async () => {
    if (!thread?.next_before || loading || pagingRef.current) return;
    const version = ++requestVersion.current;
    pagingRef.current = true;
    setLoading(true);
    try {
      const data = await api<PublicConversationThread>(`/api/watch/${encodeURIComponent(token)}/conversation?date=${thread.selected_date}&before=${encodeURIComponent(thread.next_before)}`);
      if (version === requestVersion.current && mounted.current) setThread((old) => old ? { ...data, events: mergeConversationEvents(data.events, old.events) } : data);
    } catch (e) { if (version === requestVersion.current) handleError(e); }
    finally { pagingRef.current = false; if (version === requestVersion.current && mounted.current) setLoading(false); }
  };

  const sendReply = async () => {
    const value = text.trim();
    if (!value || sendingRef.current || blocked) return;
    sendingRef.current = true; setSending(true); setError(null); setNotice("");
    // A retry after a timeout reuses the key, preventing duplicate saved replies.
    if (!submission.current || submission.current.text !== value || submission.current.messageId !== replyTo) {
      submission.current = { text: value, messageId: replyTo, clientId: window.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}` };
    }
    try {
      const reply = await api<ConversationReplyEvent>(`/api/watch/${encodeURIComponent(token)}/replies`, { json: { text: value, client_id: submission.current.clientId, message_id: replyTo } });
      if (!mounted.current || roomRef.current !== token) return;
      setText(""); setReplyTo(null); submission.current = null; setToday(reply.date);
      if (!selectedDate || selectedDate === reply.date) {
        setThread((old) => old?.selected_date === reply.date ? { ...old, events: mergeConversationEvents(old.events, [reply]) } : old);
        await load(true);
      } else { setSelectedDate(""); setThread(null); }
      setNotice("답글을 보냈어요. 보낸 분이 확인할 수 있어요.");
    } catch (e) { handleError(e); }
    finally { sendingRef.current = false; if (mounted.current) setSending(false); }
  };

  if (blocked) return <Shell><h1 className="text-3xl font-extrabold">대화방에 들어갈 수 없어요</h1><p role="alert" className="mt-5 text-xl leading-9">{error}<br />보낸 분께 새 영상 편지 링크를 부탁해 주세요.</p></Shell>;

  const dates = Array.from(new Set([today, ...(thread?.days.map((d) => d.date) || []), ...(selectedDate ? [selectedDate] : [])])).sort().reverse();
  const isToday = !selectedDate || selectedDate === today;
  return <Shell>
    <header className="mb-6 border-b border-[#e6e3d7] pb-6"><p className="mb-3 flex items-center gap-2 text-lg font-bold text-[#315d4b]"><Heart size={23} /> 온기 · 영상 편지</p><h1 className="text-[30px] font-extrabold leading-snug">{thread ? `${thread.child_name}님과 나누는 이야기` : "우리의 대화방"}</h1><p className="mt-3 text-lg leading-8 text-stone-600">영상을 보고 아래에 답글을 남겨 주세요.<br />새 영상도 이 대화방에 도착해요.</p></header>
    {error && <div className="mb-5" role="alert"><Notice tone="error">{error} <button className="min-h-12 px-2 font-bold underline" onClick={() => load()}>다시 불러오기</button></Notice></div>}
    <label htmlFor="senior-conversation-day" className="mb-2 block text-lg font-bold">대화 날짜</label>
    <select disabled={sending} id="senior-conversation-day" value={selectedDate || today} onChange={(e) => selectDay(e.target.value)} className="mb-4 min-h-16 w-full rounded-2xl border-2 border-[#cbd9ce] bg-white px-4 py-3 text-xl font-bold text-[#315d4b]">{dates.map((date) => <option key={date} value={date}>{date === today ? "오늘 · " : "지난 대화 · "}{formatConversationDate(date)}</option>)}</select>
    {!isToday && <button disabled={sending} onClick={() => selectDay(today)} className="mb-5 min-h-14 w-full rounded-2xl bg-[#e9f0e9] px-4 py-3 text-lg font-bold text-[#315d4b]">오늘 대화로 돌아가기</button>}
    {thread?.has_more && <Button variant="secondary" loading={loading} onClick={older} className="mb-5 w-full !text-lg">이 날짜의 앞선 대화 보기</Button>}
    {!thread ? <Spinner label="대화를 불러오고 있어요" /> : <>
      <p className="mb-5 text-center text-base text-stone-500">{formatConversationDate(thread.selected_date)}{isToday ? " · 오늘" : " · 지난 대화"}</p>
      <ol aria-label="영상과 답글" className="space-y-6">{thread.events.map((event) => <li key={`${event.type}-${event.id}`}>
        {event.type === "video" ? <SeniorVideo event={event} token={token} childName={thread.child_name} onReply={() => { if (sending) return; setReplyTo(event.id); composer.current?.focus(); }} /> : <article className="ml-6 rounded-[24px] rounded-br-md border border-[#d8e3d2] bg-[#e9f0e2] p-5"><p className="mb-2 text-base font-bold text-[#315d4b]">내가 남긴 답글{event.message_id ? " · 영상에 대한 답글" : ""}</p><p className="whitespace-pre-wrap break-words text-[22px] leading-9 [overflow-wrap:anywhere]">{event.text}</p><time dateTime={event.created_at} className="mt-3 block text-sm text-stone-500">{formatConversationTime(event.created_at)}</time></article>}
      </li>)}</ol>
      {!thread.events.length && <div className="rounded-3xl border border-dashed border-[#d8dfd0] bg-white px-5 py-9 text-center"><p className="text-xl leading-9">{isToday ? "오늘은 아직 영상 편지가 없어요. 먼저 안부를 남겨 보세요." : "이 날짜에는 대화가 없어요."}</p>{thread.days.some((d) => d.date !== today && d.video_count > 0) && <button disabled={sending} onClick={() => selectDay(thread.days.find((d) => d.video_count > 0 && d.date !== today)!.date)} className="mt-5 min-h-14 rounded-2xl bg-[#315d4b] px-5 py-3 text-xl font-bold text-white">지난 영상 편지 보기</button>}</div>}
    </>}
    <section className="mt-8 rounded-[28px] border-2 border-[#d5dfcf] bg-white p-5 sm:p-6" aria-labelledby="reply-title"><h2 id="reply-title" className="text-2xl font-extrabold">답글 남기기</h2><p className="mt-2 text-lg leading-8 text-stone-600">{isToday ? "짧은 안부도 좋아요. 하고 싶은 말을 적어 주세요." : "지난 영상에 답글을 남겨도 오늘 날짜의 대화에 저장돼요."}</p>{replyTo !== null && <div className="mt-4 flex items-center justify-between gap-2 rounded-xl bg-[#f0f4ea] px-3 py-2 text-base"><span>선택한 영상에 답글을 쓰고 있어요.</span><button disabled={sending} onClick={() => setReplyTo(null)} className="min-h-12 px-2 font-bold underline">선택 취소</button></div>}<label htmlFor="senior-reply" className="sr-only">보낼 답글</label><textarea id="senior-reply" ref={composer} value={text} disabled={sending} onChange={(e) => setText(e.target.value)} maxLength={1000} rows={4} placeholder="예: 영상 잘 봤다. 오늘은 산책도 다녀왔어." className="mt-4 w-full rounded-2xl border-2 border-[#dce3d5] bg-[#fcfdf9] p-4 text-[22px] leading-9 outline-none focus:border-[#315d4b]" /><p className="mt-1 text-right text-sm text-stone-500">{text.length} / 1,000자</p><Button onClick={sendReply} loading={sending} disabled={!text.trim() || !thread} className="mt-4 min-h-16 w-full !text-xl"><Send size={23} /> {sending ? "보내고 있어요" : "답글 보내기"}</Button><p role="status" aria-live="polite" className="mt-3 text-lg font-bold leading-8 text-[#315d4b]">{notice}</p></section>
    <footer className="mt-7 text-base leading-8 text-stone-500"><p>한국 시간 밤 12시가 지나면 새 날짜의 대화가 시작돼요. 지난 이야기는 대화 날짜에서 다시 볼 수 있어요.</p><p className="mt-3">이 영상은 보낸 분이 승인한 말을 AI 목소리와 얼굴로 만든 영상이에요. 답글은 보낸 분에게 전달되고 월간 대화 기록에 활용돼요.</p></footer>
  </Shell>;
}

function SeniorVideo({ event, token, childName, onReply }: { event: ConversationVideoEvent; token: string; childName: string; onReply: () => void }) {
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
  return <article className="overflow-hidden rounded-[26px] border border-[#e4e6da] bg-white p-4 shadow-sm sm:p-5"><p className="mb-3 text-lg font-bold text-[#315d4b]">{childName}님이 보낸 영상 편지</p><div className="relative aspect-[4/5] overflow-hidden rounded-2xl bg-black"><video ref={video} src={m.video_url || undefined} poster={m.poster_url || undefined} controls={started} playsInline preload="metadata" onPlay={viewed} onEnded={() => setEnded(true)} onTimeUpdate={(e) => setTime(e.currentTarget.currentTime)} onError={() => setError("영상을 불러오지 못했어요. 링크 기간이 지났다면 보낸 분께 새 링크를 부탁해 주세요.")} className="h-full w-full object-contain" />{(!started || ended) && <button onClick={play} className="absolute inset-0 flex flex-col items-center justify-center gap-4 bg-black/25" aria-label={ended ? "영상 다시 보기" : "영상 재생"}><span className="flex h-24 w-24 items-center justify-center rounded-full bg-[#ffe17f] text-stone-900 shadow-xl">{ended ? <RotateCcw size={42} /> : <Play size={44} className="ml-1 fill-current" />}</span><span className="rounded-full bg-black/70 px-5 py-3 text-xl font-bold text-white">{ended ? "다시 보기" : "눌러서 보기"}</span></button>}</div>{caption && <p className="mt-4 text-center text-2xl font-bold leading-9">{caption}</p>}{error && <p role="alert" className="mt-3 text-lg leading-8 text-red-700">{error}</p>}<p className="mt-4 whitespace-pre-wrap break-words text-xl leading-9">{m.script}</p><time dateTime={event.created_at} className="mt-3 block text-sm text-stone-500">{formatConversationTime(event.created_at)}</time><button onClick={onReply} className="mt-4 min-h-14 w-full rounded-2xl border-2 border-[#cbd9ce] px-4 py-3 text-lg font-bold text-[#315d4b]">이 영상에 답글 남기기</button></article>;
}

function Shell({ children }: { children: React.ReactNode }) {
  return <main className="mx-auto min-h-screen max-w-xl bg-[#fff8ef] px-5 pb-12 pt-7 text-stone-900 sm:px-8">{children}</main>;
}
