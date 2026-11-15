"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { CalendarDays, ChevronDown, FileText, MessageCircle, Pencil, PenLine, RefreshCw } from "lucide-react";
import { DashboardShell } from "@/components/DashboardShell";
import { ChatCalendar } from "@/components/conversations/ChatCalendar";
import { ConversationEvents } from "@/components/conversations/ConversationEvents";
import { MonthlyPortfolio } from "@/components/conversations/MonthlyPortfolio";
import { RecipientForm } from "@/components/conversations/RecipientForm";
import { Button, Card, LinkButton, Notice, Spinner } from "@/components/ui";
import { api, errorText } from "@/lib/api";
import { formatConversationDate, type ConversationEvent, type ConversationFeed, type Recipient } from "@/lib/conversations";
import { byDay, useChatFeed } from "@/lib/useChatFeed";
import { useMe } from "@/lib/useMe";

const DATE = /^\d{4}-\d{2}-\d{2}$/;

export default function ConversationPage() {
  const params = useParams<{ id: string }>();
  const recipientId = Number(params.id);
  const { me } = useMe();
  const ready = Boolean(me);
  const [tab, setTab] = useState<"conversation" | "portfolio">("conversation");
  const [recipient, setRecipient] = useState<Recipient | null>(null);
  const [childName, setChildName] = useState("");
  const [calendarOpen, setCalendarOpen] = useState(false);
  const [editing, setEditing] = useState(false);
  const [deleting, setDeleting] = useState<string | null>(null);
  const validId = Number.isSafeInteger(recipientId) && recipientId > 0;

  const feed = useChatFeed<ConversationFeed>({
    room: String(recipientId),
    enabled: ready && validId,
    active: tab === "conversation",
    refreshMs: 15000,
    fetchFeed: (query) => api<ConversationFeed>(`/api/conversations/${recipientId}/feed${query}`),
    onPage: (res) => { setRecipient(res.recipient); setChildName(res.child_name); },
    initialFocus: () => {
      const requested = new URLSearchParams(window.location.search).get("date");
      return requested && DATE.test(requested) ? requested : undefined;
    },
  });
  const { chat, days, today, focusDate, isLive, loading, refreshing, loadingOlder, loadingNewer, error, setError, refresh, retry } = feed;

  useEffect(() => { setRecipient(null); }, [recipientId]);

  const jumpTo = (date: string) => {
    setTab("conversation");
    setCalendarOpen(false);
    void feed.jumpTo(date);
  };

  const deleteEvent = async (event: ConversationEvent) => {
    const video = event.type === "video";
    if (!confirm(video
      ? "이 영상 편지를 지울까요?\n영상은 다시 볼 수 없고, 이 영상으로 보낸 링크로는 대화방에 들어올 수 없어요. 이 영상에 남긴 답글은 그대로 남아요."
      : "이 답글을 지울까요?\n지운 답글은 되돌릴 수 없어요.")) return;
    const key = `${event.type}-${event.id}`;
    setDeleting(key);
    try {
      await api(video ? `/api/messages/${event.id}` : `/api/recipients/${recipientId}/replies/${event.id}`, { method: "DELETE" });
      feed.hideEvent(key);
      setError(null);
      void refresh();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setDeleting(null);
    }
  };

  const showLatest = () => {
    setTab("conversation");
    setCalendarOpen(false);
    feed.showLatest();
  };
  const editRecipient = recipient && "is_primary" in recipient ? recipient : null;
  const recipientName = recipient?.nickname ?? "상대";
  const pastDays = days.filter((day) => day.date !== today);

  if (!Number.isSafeInteger(recipientId) || recipientId < 1) return <DashboardShell back="/letters"><Notice tone="error">올바른 대화방 주소가 아니에요.</Notice><LinkButton href="/letters" variant="secondary" className="mt-5">편지함으로 돌아가기</LinkButton></DashboardShell>;
  if (!me) return <DashboardShell back="/letters"><Spinner label="대화방을 불러오고 있어요" /></DashboardShell>;

  return (
    <DashboardShell back="/letters" onNotification={() => { void refresh(); }}>
      <div className="flex flex-wrap items-start justify-between gap-5">
        <div><p className="text-[10px] font-bold tracking-[0.16em] text-[#a77c65]">A LITTLE CLOSER EVERY DAY</p><h1 className="mt-3 text-[27px] font-bold tracking-tight text-[#2b3d30] sm:text-[34px]">{recipient ? `${recipient.nickname}와 나눈 이야기` : "우리의 대화"}</h1><p className="mt-3 text-sm leading-7 text-[#7c8775]">영상에 담은 마음과 돌아온 안부를 하루하루 이어가요.</p></div>
        <div className="flex flex-wrap gap-2">{editRecipient && <Button variant="secondary" onClick={() => setEditing((value) => !value)} aria-expanded={editing} aria-controls="edit-recipient" className="!text-xs"><Pencil size={15} />대상자 정보</Button>}{recipient && <LinkButton href={`/messages/new?recipient_id=${recipientId}`}><PenLine size={17} />영상 편지 쓰기</LinkButton>}</div>
      </div>
      {editing && editRecipient && <Card className="mt-6 !border-[#cfdcc7] sm:p-7"><div id="edit-recipient"><h2 className="mb-6 text-lg font-bold text-[#315d4b]">대화 대상자 정보</h2><RecipientForm recipient={editRecipient as Recipient} onCancel={() => setEditing(false)} onSaved={(updated) => { setRecipient(updated); setEditing(false); void refresh(); }} /></div></Card>}

      <div className="mb-7 mt-8 flex gap-1 border-b border-[#e1e6d9]" aria-label="대화방 보기 선택"><button type="button" aria-pressed={tab === "conversation"} onClick={() => setTab("conversation")} className={`inline-flex min-h-12 items-center gap-2 border-b-2 px-4 text-sm font-bold ${tab === "conversation" ? "border-[#315d4b] text-[#315d4b]" : "border-transparent text-[#93a087]"}`}><MessageCircle size={17} />날짜별 대화</button><button type="button" aria-pressed={tab === "portfolio"} onClick={() => setTab("portfolio")} className={`inline-flex min-h-12 items-center gap-2 border-b-2 px-4 text-sm font-bold ${tab === "portfolio" ? "border-[#315d4b] text-[#315d4b]" : "border-transparent text-[#93a087]"}`}><FileText size={17} />월간 포트폴리오</button></div>

      {tab === "portfolio" ? <MonthlyPortfolio recipientId={recipientId} recipientName={recipient?.nickname ?? "대상자"} onOpenDate={(date) => { void jumpTo(date); }} /> : (
        <div className="grid items-start gap-6 xl:grid-cols-[230px_minmax(0,1fr)]">
          <aside className="min-w-0 rounded-[22px] border border-[#e1e6da] bg-white p-5 xl:sticky xl:top-28">
            <h2 className="flex items-center gap-2 text-sm font-bold text-[#4d6546]"><CalendarDays size={17} />날짜별 편지함</h2>
            <button type="button" onClick={showLatest} aria-pressed={isLive && focusDate === null} className={`mt-4 flex min-h-11 w-full items-center justify-between rounded-xl px-3 text-sm font-bold ${isLive && focusDate === null ? "bg-[#315d4b] text-white" : "bg-[#f0f4e9] text-[#6f865f]"}`}>최근 대화<span className="text-[10px] font-normal">{Number(today.slice(5, 7))}/{Number(today.slice(8))}</span></button>
            <p className="mt-5 text-xs font-semibold text-stone-500">날짜로 찾기</p>
            <button type="button" onClick={() => setCalendarOpen((open) => !open)} aria-expanded={calendarOpen} aria-controls="chat-calendar" className="mt-2 flex min-h-11 w-full items-center justify-between rounded-xl border border-[#dfe5d7] bg-[#fcfdf9] px-3 text-xs text-[#566b4e] focus:outline-none focus:ring-2 focus:ring-[#aabc9c]">{focusDate ? formatConversationDate(focusDate) : "대화한 날 고르기"}<ChevronDown size={14} className={calendarOpen ? "rotate-180" : ""} /></button>
            {calendarOpen && <div id="chat-calendar" className="mt-2"><ChatCalendar activeDays={days.map((day) => day.date)} selected={focusDate} today={today} onSelect={(date) => { void jumpTo(date); }} /></div>}
            <p className="mb-2 mt-5 text-[10px] font-semibold tracking-wide text-[#a0ad94]">지난 대화</p>
            <ul className="flex max-h-64 gap-2 overflow-auto pb-1 xl:max-h-[360px] xl:flex-col">{pastDays.map((day) => <li key={day.date} className="shrink-0 xl:shrink"><button type="button" onClick={() => { void jumpTo(day.date); }} aria-pressed={focusDate === day.date} className={`min-h-12 w-full rounded-xl px-3 py-2 text-left ${focusDate === day.date ? "bg-[#eaf1e4] text-[#315d4b]" : "text-[#788970] hover:bg-[#f4f6ef]"}`}><span className="block text-xs font-semibold">{formatConversationDate(day.date)}</span><span className="mt-1 block text-[10px] opacity-70">영상 {day.video_count} · 답글 {day.reply_count}</span></button></li>)}</ul>
            {chat && pastDays.length === 0 && <p className="text-xs leading-6 text-stone-400">지난 대화가 이곳에 쌓여요.</p>}
            <p className="mt-5 border-t border-[#eef1e7] pt-4 text-[10px] leading-6 text-stone-400">모든 날짜는 한국 시간 기준이에요.</p>
          </aside>

          <section aria-label="대화 기록" className="min-w-0">
            <div className="mb-4 flex flex-wrap items-center justify-between gap-3"><div><h2 className="font-bold text-[#3f553e]">대화 기록</h2><p className="mt-1.5 text-xs text-stone-400">{chat?.hasNewer ? "지난 대화를 보고 있어요. 아래에서 이후 대화를 이어 볼 수 있어요." : "위로 올리면 이전 대화를 더 볼 수 있어요. 새 답글은 자동으로 불러와요."}</p></div><button type="button" onClick={retry} disabled={refreshing || loading} className="inline-flex min-h-10 items-center gap-1.5 rounded-xl px-3 text-xs font-semibold text-[#899c7c] hover:bg-[#edf2e6] disabled:opacity-50"><RefreshCw size={13} className={refreshing || loading ? "animate-spin" : ""} />새로고침</button></div>
            {error && <div role="alert" className="mb-4"><Notice tone="error">{error}<button type="button" onClick={retry} className="ml-3 font-bold underline">다시 시도</button></Notice></div>}
            <div ref={feed.scroller} onScroll={feed.onScroll} aria-busy={loading} className="relative h-[70vh] min-h-[420px] overflow-y-auto overscroll-contain rounded-[22px] border border-[#e4e9dc] bg-[#fbfcf8] px-3 pb-6 [overflow-anchor:none] sm:px-6 xl:h-[calc(100vh-27rem)] xl:min-h-[460px]">
              <div ref={feed.content}>
                {!chat ? (loading ? <div className="py-20"><Spinner label="대화를 불러오고 있어요" /></div> : null)
                  : chat.events.length === 0 ? <div className="py-14 text-center"><MessageCircle size={34} className="mx-auto text-[#a1b394]" /><h3 className="mt-4 font-bold text-[#58734f]">오늘은 어떤 안부를 전할까요?</h3><p className="mx-auto mt-3 max-w-md text-sm leading-7 text-stone-500">영상 편지를 만들고 대화방 링크를 공유해 보세요. 상대는 로그인 없이 영상을 보고 답글을 남길 수 있어요.</p><LinkButton href={`/messages/new?recipient_id=${recipientId}`} className="mt-6"><PenLine size={17} />영상 편지 쓰기</LinkButton></div>
                  : <>
                    {chat.hasOlder
                      ? <div className="pt-5 text-center"><Button variant="secondary" loading={loadingOlder} onClick={() => { void feed.loadOlder(); }} className="!text-xs">이전 대화 보기</Button></div>
                      : <p className="pt-6 text-center text-[11px] text-stone-400">{recipientName}와 나눈 첫 대화예요</p>}
                    {byDay(chat.events).map(([day, items]) => <section key={day} data-day={day} aria-label={formatConversationDate(day)}>
                      <div className="sticky top-0 z-10 flex justify-center py-3"><span className={`rounded-full px-3 py-1 text-[11px] font-semibold shadow-sm ring-1 ${focusDate === day ? "bg-[#315d4b] text-white ring-[#315d4b]" : "bg-white/95 text-[#6f7f66] ring-[#e4e9dc]"}`}>{formatConversationDate(day)}{day === today ? " · 오늘" : ""}</span></div>
                      <ConversationEvents events={items} recipientName={recipientName} childName={childName || me.user.name} onDelete={(event) => { void deleteEvent(event); }} deleting={deleting} />
                    </section>)}
                    {chat.hasNewer && <div className="flex flex-wrap justify-center gap-2 pt-7"><Button variant="secondary" loading={loadingNewer} onClick={() => { void feed.loadNewer(); }} className="!text-xs">이후 대화 보기</Button><Button variant="secondary" onClick={showLatest} className="!text-xs">최근 대화로</Button></div>}
                  </>}
              </div>
            </div>
            <div className="mt-6 text-center"><p className="mb-4 text-xs leading-6 text-stone-400">새 영상 편지는 보낸 날짜의 대화에 이어져요.</p><LinkButton href={`/messages/new?recipient_id=${recipientId}`}><PenLine size={17} />답글에 영상 편지로 답하기</LinkButton></div>
          </section>
        </div>
      )}
    </DashboardShell>
  );
}
