"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { ChevronRight, Inbox, MessageCircle, Plus, RefreshCw, Video } from "lucide-react";
import { DashboardShell } from "@/components/DashboardShell";
import { RecipientForm } from "@/components/conversations/RecipientForm";
import { Button, Card, Notice, Spinner } from "@/components/ui";
import { api, errorText } from "@/lib/api";
import { formatConversationDate, formatConversationTime, kstDate, type Recipient } from "@/lib/conversations";
import { useMe } from "@/lib/useMe";

export default function LettersPage() {
  const { me } = useMe();
  const [recipients, setRecipients] = useState<Recipient[] | null>(null);
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const refresh = useCallback(async () => {
    setRefreshing(true);
    try {
      setRecipients(await api<Recipient[]>("/api/recipients"));
      setError(null);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    if (!me) return;
    void refresh();
    const timer = window.setInterval(() => { if (document.visibilityState === "visible") void refresh(); }, 20000);
    const onFocus = () => { void refresh(); };
    window.addEventListener("focus", onFocus);
    return () => { window.clearInterval(timer); window.removeEventListener("focus", onFocus); };
  }, [me, refresh]);

  return (
    <DashboardShell onNotification={() => { void refresh(); }}>
      <div className="flex flex-wrap items-start justify-between gap-5">
        <div>
          <p className="text-[10px] font-bold tracking-[0.16em] text-[#a77c65]">OUR LITTLE CONVERSATIONS</p>
          <h1 className="mt-3 text-[28px] font-bold tracking-tight text-[#2b3d30] sm:text-[34px]">영상 편지함</h1>
          <p className="mt-3 max-w-xl text-sm leading-7 text-[#7c8775]">소중한 사람을 고르면 영상 편지와 답글이 날짜별로 모여 있어요.</p>
        </div>
        {me && <Button onClick={() => setAdding((value) => !value)} aria-expanded={adding} aria-controls="add-recipient"><Plus size={18} />대화 대상자 추가</Button>}
      </div>

      {adding && <Card className="mt-7 !border-[#ceddcc] sm:p-7"><div id="add-recipient"><h2 className="mb-6 text-lg font-bold text-[#315d4b]">누구에게 마음을 전할까요?</h2><RecipientForm onCancel={() => setAdding(false)} onSaved={(recipient) => { setRecipients((current) => [...(current ?? []), recipient]); setAdding(false); void refresh(); }} /></div></Card>}

      <div className="mt-7 rounded-2xl border border-[#e5e8dc] bg-[#eff3e9] px-5 py-4 text-sm leading-7 text-[#62745b]">대화는 매일 밤 12시, 한국 시간 기준으로 새로 시작해요. 지난 대화는 각 대상자의 날짜 목록에서 언제든 다시 볼 수 있어요.</div>
      {error && <div role="alert" className="mt-5"><Notice tone="error"><span>{error}</span><button type="button" onClick={() => { void refresh(); }} className="ml-3 font-bold underline">다시 불러오기</button></Notice></div>}

      <div className="mb-5 mt-8 flex items-center justify-between gap-3">
        <h2 className="font-bold text-[#3d503e]">대화 대상자 {recipients !== null && <span className="ml-1 text-[#8a9a80]">{recipients.length}</span>}</h2>
        <button type="button" onClick={() => { void refresh(); }} disabled={refreshing || !me} className="inline-flex min-h-10 items-center gap-2 rounded-xl px-3 text-xs text-stone-500 hover:bg-[#e9eee3] disabled:opacity-50"><RefreshCw size={14} className={refreshing ? "animate-spin" : ""} />새로고침</button>
      </div>

      {!me || (recipients === null && !error) ? <Spinner label="편지함을 불러오고 있어요" /> : recipients?.length === 0 ? (
        <Card className="py-14 text-center"><Inbox className="mx-auto h-10 w-10 text-[#91a68a]" /><h2 className="mt-5 text-lg font-bold">첫 대화를 시작해 보세요</h2><p className="mx-auto mt-2 max-w-sm text-sm leading-7 text-stone-500">대화할 분을 추가하면 영상 편지와 답글을 한곳에서 이어갈 수 있어요.</p><Button onClick={() => setAdding(true)} className="mt-6"><Plus size={18} />대상자 추가하기</Button></Card>
      ) : recipients ? (
        <ul className="grid gap-5 sm:grid-cols-2 xl:grid-cols-3">
          {recipients.map((recipient) => <li key={recipient.id}>
            <Link href={`/conversations/${recipient.id}`} className="group flex h-full flex-col rounded-[24px] border border-[#e1e6dc] bg-white p-6 shadow-[0_5px_18px_rgba(32,42,32,0.03)] transition-colors hover:border-[#9bb594]">
              <div className="flex items-start justify-between gap-3"><span className="flex h-14 w-14 items-center justify-center rounded-[20px] bg-[#edf2e8] text-xl font-bold text-[#577850]" aria-hidden="true">{recipient.nickname.slice(0, 1)}</span><span className="rounded-full bg-[#f6f2eb] px-3 py-1 text-xs text-[#9b8069]">{recipient.relation}</span></div>
              <h3 className="mt-5 text-xl font-bold text-[#2b3d30]">{recipient.nickname}</h3>
              <p className="mt-2 line-clamp-2 min-h-12 break-words text-sm leading-6 text-stone-500">{recipient.last_preview || "첫 번째 영상 편지로 안부를 전해 보세요."}</p>
              <div className="mb-5 mt-4 flex flex-wrap gap-x-4 gap-y-2 text-xs text-[#74846c]"><span className="inline-flex items-center gap-1.5"><Video size={14} />영상 {recipient.video_count}</span><span className="inline-flex items-center gap-1.5"><MessageCircle size={14} />답글 {recipient.reply_count}</span></div>
              <div className="mt-auto flex items-end justify-between gap-3 border-t border-[#eff1e9] pt-4"><div className="text-xs leading-6 text-stone-500">{recipient.today_reply_count > 0 || recipient.today_video_count > 0 ? <p className="font-semibold text-[#577850]">오늘 영상 {recipient.today_video_count} · 답글 {recipient.today_reply_count}</p> : <p>오늘의 안부를 건네 보세요</p>}{recipient.last_activity_at && <p className="text-[11px]">{kstDate(new Date(recipient.last_activity_at)) === kstDate() ? `오늘 ${formatConversationTime(recipient.last_activity_at)}` : formatConversationDate(kstDate(new Date(recipient.last_activity_at)))}</p>}</div><ChevronRight size={19} className="shrink-0 text-[#7d9974] transition-transform group-hover:translate-x-1" /></div>
            </Link>
          </li>)}
        </ul>
      ) : null}
    </DashboardShell>
  );
}
