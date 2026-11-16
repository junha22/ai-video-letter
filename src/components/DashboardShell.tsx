"use client";

import Link from "next/link";
import { AlertTriangle, ChevronLeft, Heart, House, Leaf, Mail, Settings } from "lucide-react";
import { usePathname } from "next/navigation";
import { useState, type ReactNode } from "react";
import { api } from "@/lib/api";
import type { NotificationItem } from "@/lib/types";
import { NotificationBell } from "./Notifications";

/** 로그인한 사용자 화면의 공통 레이아웃. API와 인증은 각 페이지가 유지한다. */
export function DashboardShell({ children, back, onNotification }: {
  children: ReactNode;
  back?: string;
  onNotification?: (n: NotificationItem) => void;
}) {
  const pathname = usePathname();
  // 답장 분석의 '바로 연락 필요'(reply_alert)는 읽을 때까지 화면 맨 위에 띄운다
  const [alerts, setAlerts] = useState<NotificationItem[]>([]);
  const onItems = (items: NotificationItem[]) => {
    const next = items.filter((n) => n.kind === "reply_alert" && !n.read);
    setAlerts((prev) => (prev.length === next.length && prev.every((n, i) => n.id === next[i].id) ? prev : next));
  };
  const confirmAlert = (id: number) => {
    setAlerts((list) => list.filter((n) => n.id !== id));
    void api(`/api/notifications/${id}/read`, { method: "POST" }).catch(() => undefined);
  };
  const pageLabel = pathname.startsWith("/onboarding/") ? "편지를 위한 준비" : pathname === "/letters" ? "영상 편지함" : pathname.startsWith("/conversations/") ? "날짜별 대화와 월간 기록" : pathname.startsWith("/messages/") ? "마음을 전하는 편지" : pathname === "/settings" ? "나의 설정" : "오늘의 온기";
  const navigation = (
    <>
      <Link href="/home" aria-current={pathname === "/home" ? "page" : undefined} className={`flex items-center gap-3 rounded-2xl px-4 py-3 font-bold ${pathname === "/home" ? "bg-[#e8eee6] text-[#315d4b]" : "text-stone-600 hover:bg-[#eeeee5]"}`}><House size={20} />홈</Link>
      <Link href="/letters" aria-current={pathname === "/letters" || pathname.startsWith("/conversations/") ? "page" : undefined} className={`flex items-center gap-3 rounded-2xl px-4 py-3 ${pathname === "/letters" || pathname.startsWith("/conversations/") ? "bg-[#e8eee6] font-bold text-[#315d4b]" : "text-stone-600 hover:bg-[#eeeee5]"}`}><Mail size={20} />영상 편지함</Link>
      <Link href="/settings" aria-current={pathname === "/settings" ? "page" : undefined} className={`flex items-center gap-3 rounded-2xl px-4 py-3 ${pathname === "/settings" ? "bg-[#e8eee6] font-bold text-[#315d4b]" : "text-stone-600 hover:bg-[#eeeee5]"}`}><Settings size={20} />설정</Link>
    </>
  );

  return (
    <div className="min-h-screen bg-[#f8f7f2] text-[#2e342f] selection:bg-[#dce8d8] [&_a:focus-visible]:outline [&_a:focus-visible]:outline-2 [&_a:focus-visible]:outline-offset-4 [&_a:focus-visible]:outline-[#315d4b]">
      <a href="#dashboard-content" className="sr-only z-50 focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:rounded-full focus:bg-white focus:p-3">본문으로 이동</a>
      <aside className="fixed inset-y-0 left-0 hidden w-[252px] flex-col border-r border-[#e4e5da] bg-[#fdfcf8] px-6 py-9 lg:flex">
        <Link href="/home" className="flex items-center gap-3 text-[28px] font-black tracking-tight text-[#315d4b]"><span className="flex h-10 w-10 -rotate-6 items-center justify-center rounded-[14px] bg-[#315d4b] text-white"><Heart size={21} strokeWidth={1.7} aria-hidden="true" /></span>온기</Link>
        <p className="mt-3 text-xs leading-6 text-stone-500">마음을 잇는 영상 편지</p>
        <p className="mb-3 mt-12 px-4 text-[10px] font-semibold tracking-widest text-[#9aab94]">마음을 잇는 공간</p>
        <nav aria-label="주 메뉴" className="space-y-2">{navigation}</nav>
        <div className="mt-auto rounded-[20px] border border-[#e5eadd] bg-[#f0f4ea] p-5"><Leaf size={23} strokeWidth={1.5} className="mb-3 text-[#719175]" aria-hidden="true" /><p className="text-xs font-semibold leading-6 text-[#536d54]">짧은 안부도<br />큰 마음이 될 수 있어요.</p><p className="mt-3 text-[10px] text-[#91a08b]">멀리 있어도, 마음은 가까이.</p></div>
      </aside>
      <div className="lg:pl-[252px]">
        <header className="sticky top-0 z-30 flex min-h-16 items-center justify-between border-b border-[#e4e5da] bg-[#f8f7f2]/95 px-5 backdrop-blur sm:min-h-20 sm:px-10">
          <div className="flex min-w-0 items-center gap-2">
            {back && <Link href={back} aria-label="뒤로" className="rounded-full p-2 text-[#315d4b] hover:bg-[#e8eee6]"><ChevronLeft size={23} /></Link>}
            <Link href="/home" className="text-2xl font-black text-[#315d4b] lg:hidden">온기</Link>
            <span className="hidden items-center gap-3 text-xs text-[#8e9989] lg:flex">온기<span className="h-1 w-1 rounded-full bg-[#cbd6c4]" /> <span className="text-[#566a54]">{pageLabel}</span></span>
          </div>
          <div className="flex items-center gap-2"><div className="rounded-full border border-[#e8ece1] bg-white"><NotificationBell onNew={onNotification} onItems={onItems} /></div><Link href="/settings" aria-label="설정" className="rounded-full border border-[#e8ece1] bg-white p-2 text-stone-600 hover:bg-[#e8eee6]"><Settings size={22} /></Link></div>
        </header>
        {alerts.length > 0 && <div role="alert" className="border-b border-[#8f2a18] bg-[#A8321E] px-5 py-3 text-white sm:px-10">
          {alerts.slice(0, 3).map((n) => <div key={n.id} className="flex flex-wrap items-center gap-x-4 gap-y-2 py-1">
            <p className="flex min-w-0 flex-1 items-center gap-2 text-sm font-bold"><AlertTriangle size={18} className="shrink-0" />{n.text}</p>
            <div className="flex gap-2">{n.recipient_id && <Link href={`/conversations/${n.recipient_id}`} onClick={() => confirmAlert(n.id)} className="rounded-full bg-white px-3 py-1.5 text-xs font-bold text-[#A8321E]">대화방에서 보기</Link>}<button type="button" onClick={() => confirmAlert(n.id)} className="rounded-full border border-white/70 px-3 py-1.5 text-xs font-bold">확인했어요</button></div>
          </div>)}
        </div>}
        <details className="border-b border-[#e4e5da] px-5 py-3 lg:hidden">
          <summary className="cursor-pointer text-sm font-bold text-[#315d4b]">메뉴</summary>
          <nav aria-label="모바일 주 메뉴" className="mt-3 space-y-1 pb-2">{navigation}</nav>
        </details>
        <main id="dashboard-content" className="mx-auto max-w-[1280px] px-5 py-7 sm:px-10 sm:py-10">{children}</main>
      </div>
    </div>
  );
}

