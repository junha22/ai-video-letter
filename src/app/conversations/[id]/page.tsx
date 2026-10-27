"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useParams } from "next/navigation";
import { CalendarDays, ChevronLeft, FileText, MessageCircle, Pencil, PenLine, RefreshCw } from "lucide-react";
import { DashboardShell } from "@/components/DashboardShell";
import { ConversationEvents } from "@/components/conversations/ConversationEvents";
import { MonthlyPortfolio } from "@/components/conversations/MonthlyPortfolio";
import { RecipientForm } from "@/components/conversations/RecipientForm";
import { Button, Card, LinkButton, Notice, Spinner } from "@/components/ui";
import { api, errorText } from "@/lib/api";
import { formatConversationDate, kstDate, mergeConversationEvents, type ConversationThread, type Recipient } from "@/lib/conversations";
import { useMe } from "@/lib/useMe";

export default function ConversationPage() {
  const params = useParams<{ id: string }>();
  const recipientId = Number(params.id);
  const { me } = useMe();
  const [date, setDate] = useState(kstDate());
  const [today, setToday] = useState(kstDate());
  const [tab, setTab] = useState<"conversation" | "portfolio">("conversation");
  const [thread, setThread] = useState<ConversationThread | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [loadingOlder, setLoadingOlder] = useState(false);
  const [editing, setEditing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [rollover, setRollover] = useState(false);
  const refreshRef = useRef<(() => Promise<void>) | null>(null);
  const loadedOlder = useRef(false);
  const selectedRef = useRef(`${recipientId}:${date}`);
  selectedRef.current = `${recipientId}:${date}`;
  const current = thread?.selected_date === date && thread.recipient.id === recipientId ? thread : null;
  const recipient = thread?.recipient.id === recipientId ? thread.recipient : null;
  const isToday = date === today;

  useEffect(() => {
    const requested = new URLSearchParams(window.location.search).get("date");
    if (requested && /^\d{4}-\d{2}-\d{2}$/.test(requested) && requested <= kstDate()) setDate(requested);
  }, [recipientId]);

  useEffect(() => {
    let previous = kstDate();
    const checkDay = () => {
      const next = kstDate();
      if (previous === next) return;
      const old = previous;
      previous = next;
      setToday(next);
      if (selectedRef.current === `${recipientId}:${old}`) { setRollover(true); setDate(next); }
    };
    const timer = window.setInterval(checkDay, 1000);
    window.addEventListener("focus", checkDay);
    return () => { window.clearInterval(timer); window.removeEventListener("focus", checkDay); };
  }, [recipientId]);

  useEffect(() => {
    if (!me || !Number.isSafeInteger(recipientId) || recipientId < 1) return;
    let active = true;
    let inFlight = false;
    loadedOlder.current = false;
    setLoading(true);
    setError(null);
    setLoadingOlder(false);
    const refresh = async () => {
      if (inFlight) return;
      inFlight = true;
      if (active) setRefreshing(true);
      try {
        const next = await api<ConversationThread>(`/api/conversations/${recipientId}?date=${encodeURIComponent(date)}`);
        if (!active) return;
        setThread((previous) => {
          if (previous?.selected_date !== date || previous.recipient.id !== recipientId) return next;
          return { ...next, events: mergeConversationEvents(previous.events, next.events), ...(loadedOlder.current ? { has_more: previous.has_more, next_before: previous.next_before } : {}) };
        });
        setToday(next.today);
        setError(null);
      } catch (e) {
        if (active) setError(errorText(e));
      } finally {
        inFlight = false;
        if (active) { setLoading(false); setRefreshing(false); }
      }
    };
    refreshRef.current = refresh;
    void refresh();
    const timer = window.setInterval(() => { if (document.visibilityState === "visible") void refresh(); }, 15000);
    const onFocus = () => { void refresh(); };
    window.addEventListener("focus", onFocus);
    return () => { active = false; refreshRef.current = null; window.clearInterval(timer); window.removeEventListener("focus", onFocus); };
  }, [me, recipientId, date]);

  const loadOlder = useCallback(async () => {
    if (!current?.has_more || !current.next_before || loadingOlder) return;
    const selected = date;
    setLoadingOlder(true);
    try {
      const next = await api<ConversationThread>(`/api/conversations/${recipientId}?date=${encodeURIComponent(selected)}&before=${encodeURIComponent(current.next_before)}`);
      if (selectedRef.current !== `${recipientId}:${selected}`) return;
      loadedOlder.current = true;
      setThread((previous) => previous?.selected_date === selected && previous.recipient.id === recipientId ? { ...previous, events: mergeConversationEvents(next.events, previous.events), has_more: next.has_more, next_before: next.next_before } : previous);
      setError(null);
    } catch (e) {
      if (selectedRef.current === `${recipientId}:${selected}`) setError(errorText(e));
    } finally {
      if (selectedRef.current === `${recipientId}:${selected}`) setLoadingOlder(false);
    }
  }, [current, date, loadingOlder, recipientId]);

  const selectDate = (next: string) => { setDate(next); setRollover(false); };
  const openDate = (next: string) => { selectDate(next); setTab("conversation"); };
  const editRecipient = recipient && "is_primary" in recipient ? recipient as Recipient : null;

  if (!Number.isSafeInteger(recipientId) || recipientId < 1) return <DashboardShell back="/letters"><Notice tone="error">올바른 대화방 주소가 아니에요.</Notice><LinkButton href="/letters" variant="secondary" className="mt-5">편지함으로 돌아가기</LinkButton></DashboardShell>;
  if (!me) return <DashboardShell back="/letters"><Spinner label="대화방을 불러오고 있어요" /></DashboardShell>;

  return (
    <DashboardShell back="/letters" onNotification={() => { void refreshRef.current?.(); }}>
      <div className="flex flex-wrap items-start justify-between gap-5">
        <div><p className="text-[10px] font-bold tracking-[0.16em] text-[#a77c65]">A LITTLE CLOSER EVERY DAY</p><h1 className="mt-3 text-[27px] font-bold tracking-tight text-[#2b3d30] sm:text-[34px]">{recipient ? `${recipient.nickname}와 나눈 이야기` : "우리의 대화"}</h1><p className="mt-3 text-sm leading-7 text-[#7c8775]">영상에 담은 마음과 돌아온 안부를 하루하루 이어가요.</p></div>
        <div className="flex flex-wrap gap-2">{editRecipient && <Button variant="secondary" onClick={() => setEditing((value) => !value)} aria-expanded={editing} aria-controls="edit-recipient" className="!text-xs"><Pencil size={15} />대상자 정보</Button>}{recipient && <LinkButton href={`/messages/new?recipient_id=${recipientId}`}><PenLine size={17} />영상 편지 쓰기</LinkButton>}</div>
      </div>
      {editing && editRecipient && <Card className="mt-6 !border-[#cfdcc7] sm:p-7"><div id="edit-recipient"><h2 className="mb-6 text-lg font-bold text-[#315d4b]">대화 대상자 정보</h2><RecipientForm recipient={editRecipient} onCancel={() => setEditing(false)} onSaved={(updated) => { setThread((previous) => previous ? { ...previous, recipient: updated } : previous); setEditing(false); void refreshRef.current?.(); }} /></div></Card>}

      <div className="mb-7 mt-8 flex gap-1 border-b border-[#e1e6d9]" aria-label="대화방 보기 선택"><button type="button" aria-pressed={tab === "conversation"} onClick={() => setTab("conversation")} className={`inline-flex min-h-12 items-center gap-2 border-b-2 px-4 text-sm font-bold ${tab === "conversation" ? "border-[#315d4b] text-[#315d4b]" : "border-transparent text-[#93a087]"}`}><MessageCircle size={17} />날짜별 대화</button><button type="button" aria-pressed={tab === "portfolio"} onClick={() => setTab("portfolio")} className={`inline-flex min-h-12 items-center gap-2 border-b-2 px-4 text-sm font-bold ${tab === "portfolio" ? "border-[#315d4b] text-[#315d4b]" : "border-transparent text-[#93a087]"}`}><FileText size={17} />월간 포트폴리오</button></div>

      {tab === "portfolio" ? <MonthlyPortfolio recipientId={recipientId} recipientName={recipient?.nickname ?? "대상자"} onOpenDate={openDate} /> : (
        <>
          {rollover && <div className="mb-5" role="status"><Notice>새로운 하루가 시작되어 오늘의 대화로 이동했어요. 어제 나눈 이야기는 날짜 목록에서 다시 볼 수 있어요.</Notice></div>}
          <div className="grid items-start gap-6 xl:grid-cols-[230px_minmax(0,1fr)]">
            <aside className="rounded-[22px] border border-[#e1e6da] bg-white p-5 xl:sticky xl:top-28">
              <h2 className="flex items-center gap-2 text-sm font-bold text-[#4d6546]"><CalendarDays size={17} />날짜별 편지함</h2>
              <button type="button" onClick={() => selectDate(today)} aria-pressed={isToday} className={`mt-4 flex min-h-11 w-full items-center justify-between rounded-xl px-3 text-sm font-bold ${isToday ? "bg-[#315d4b] text-white" : "bg-[#f0f4e9] text-[#6f865f]"}`}>오늘의 대화<span className="text-[10px] font-normal">{Number(today.slice(5, 7))}/{Number(today.slice(8))}</span></button>
              <label htmlFor="conversation-date" className="mt-5 block text-xs font-semibold text-stone-500">날짜로 찾기<input id="conversation-date" type="date" max={today} value={date} onChange={(event) => { if (/^\d{4}-\d{2}-\d{2}$/.test(event.target.value)) selectDate(event.target.value); }} className="mt-2 min-h-11 w-full rounded-xl border border-[#dfe5d7] bg-[#fcfdf9] px-3 text-xs text-[#566b4e] outline-none focus:ring-2 focus:ring-[#aabc9c]" /></label>
              <p className="mb-2 mt-5 text-[10px] font-semibold tracking-wide text-[#a0ad94]">지난 대화</p>
              <ul className="flex max-h-64 gap-2 overflow-auto pb-1 xl:max-h-[420px] xl:flex-col">{(thread?.days ?? []).filter((day) => day.date !== today).map((day) => <li key={day.date} className="shrink-0 xl:shrink"><button type="button" onClick={() => selectDate(day.date)} aria-pressed={date === day.date} className={`min-h-12 w-full rounded-xl px-3 py-2 text-left ${date === day.date ? "bg-[#eaf1e4] text-[#315d4b]" : "text-[#788970] hover:bg-[#f4f6ef]"}`}><span className="block text-xs font-semibold">{formatConversationDate(day.date)}</span><span className="mt-1 block text-[10px] opacity-70">영상 {day.video_count} · 답글 {day.reply_count}</span></button></li>)}</ul>
              {thread && thread.days.filter((day) => day.date !== today).length === 0 && <p className="text-xs leading-6 text-stone-400">지난 대화가 이곳에 쌓여요.</p>}
              <p className="mt-5 border-t border-[#eef1e7] pt-4 text-[10px] leading-6 text-stone-400">매일 밤 12시에 새 대화로 넘어가요.<br />모든 날짜는 한국 시간 기준이에요.</p>
            </aside>

            <section aria-label="선택한 날짜의 대화" className="min-w-0">
              <div className="mb-6 flex flex-wrap items-center justify-between gap-3"><div><h2 className="font-bold text-[#3f553e]">{formatConversationDate(date)} {isToday && <span className="ml-1 text-xs font-normal text-[#879b79]">오늘</span>}</h2><p className="mt-1.5 text-xs text-stone-400">{isToday ? "답글은 자동으로 새로 불러와요." : "이날 주고받은 영상 편지와 답글이에요."}</p></div><button type="button" onClick={() => { void refreshRef.current?.(); }} disabled={refreshing} className="inline-flex min-h-10 items-center gap-1.5 rounded-xl px-3 text-xs font-semibold text-[#899c7c] hover:bg-[#edf2e6] disabled:opacity-50"><RefreshCw size={13} className={refreshing ? "animate-spin" : ""} />새로고침</button></div>
              {error && <div role="alert" className="mb-5"><Notice tone="error">{error}<button type="button" onClick={() => { void refreshRef.current?.(); }} className="ml-3 font-bold underline">다시 시도</button></Notice></div>}
              {loading && !current ? <Spinner label="그날의 이야기를 불러오고 있어요" /> : current && current.events.length === 0 ? <Card className="py-12 text-center"><MessageCircle size={34} className="mx-auto text-[#a1b394]" /><h3 className="mt-4 font-bold text-[#58734f]">{isToday ? "오늘은 어떤 안부를 전할까요?" : "이날 나눈 대화가 없어요"}</h3><p className="mx-auto mt-3 max-w-md text-sm leading-7 text-stone-500">{isToday ? "영상 편지를 만들고 대화방 링크를 공유해 보세요. 상대는 로그인 없이 영상을 보고 답글을 남길 수 있어요." : "다른 날짜를 선택하거나 오늘의 대화로 돌아가 보세요."}</p>{isToday ? <LinkButton href={`/messages/new?recipient_id=${recipientId}`} className="mt-6"><PenLine size={17} />영상 편지 쓰기</LinkButton> : <Button variant="secondary" onClick={() => selectDate(today)} className="mt-6"><ChevronLeft size={16} />오늘의 대화 보기</Button>}</Card> : current ? <>{current.has_more && <div className="mb-6 text-center"><Button variant="secondary" loading={loadingOlder} onClick={() => { void loadOlder(); }} className="!text-xs">이날의 이전 대화 더 보기</Button></div>}<ConversationEvents events={current.events} recipientName={recipient?.nickname ?? "상대"} childName={thread?.child_name || me.user.name} /><div className="mt-8 border-t border-[#e4e9dc] pt-6 text-center"><p className="mb-4 text-xs leading-6 text-stone-400">새 영상 편지는 보낸 날짜의 대화에 이어져요.</p><LinkButton href={`/messages/new?recipient_id=${recipientId}`}><PenLine size={17} />답글에 영상 편지로 답하기</LinkButton></div></> : null}
            </section>
          </div>
        </>
      )}
    </DashboardShell>
  );
}
