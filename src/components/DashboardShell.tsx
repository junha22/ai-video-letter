"use client";

import Link from "next/link";
import { Heart, House, Mail, Settings } from "lucide-react";
import type { ReactNode } from "react";
import type { NotificationItem } from "@/lib/types";
import { NotificationBell } from "./Notifications";

/** 홈에서만 사용하는 레이아웃. 다른 화면의 AppShell은 유지한다. */
export function DashboardShell({ children, onNotification }: {
  children: ReactNode;
  onNotification?: (n: NotificationItem) => void;
}) {
  const navigation = (
    <>
      <Link href="/home" aria-current="page" className="flex items-center gap-3 rounded-2xl bg-[#e8eee6] px-4 py-3 font-bold text-[#315d4b]"><House size={20} />홈</Link>
      <Link href="/home#letters" className="flex items-center gap-3 rounded-2xl px-4 py-3 text-stone-600 hover:bg-[#eeeee5]"><Mail size={20} />영상 편지함</Link>
      <Link href="/settings" className="flex items-center gap-3 rounded-2xl px-4 py-3 text-stone-600 hover:bg-[#eeeee5]"><Settings size={20} />설정</Link>
    </>
  );

  return (
    <div className="min-h-screen bg-[#f8f7f2] text-[#2e342f] selection:bg-[#dce8d8] [&_a:focus-visible]:outline [&_a:focus-visible]:outline-2 [&_a:focus-visible]:outline-offset-4 [&_a:focus-visible]:outline-[#315d4b]">
      <a href="#dashboard-content" className="sr-only z-50 focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:rounded-full focus:bg-white focus:p-3">본문으로 이동</a>
      <aside className="fixed inset-y-0 left-0 hidden w-[252px] flex-col border-r border-[#e4e5da] bg-[#fdfcf8] px-6 py-9 lg:flex">
        <Link href="/home" className="flex items-center gap-2 text-3xl font-black tracking-tight text-[#315d4b]"><Heart size={25} aria-hidden="true" />온기</Link>
        <p className="mt-3 text-xs leading-6 text-stone-500">마음을 잇는 영상 편지</p>
        <nav aria-label="주 메뉴" className="mt-12 space-y-2">{navigation}</nav>
        <p className="mt-auto border-t border-[#dde1d3] pt-6 text-sm leading-7 text-stone-500">멀리 있어도,<br />마음은 가까이.</p>
      </aside>
      <div className="lg:pl-[252px]">
        <header className="sticky top-0 z-30 flex min-h-16 items-center justify-between border-b border-[#e4e5da] bg-[#f8f7f2]/95 px-5 backdrop-blur sm:min-h-20 sm:px-10">
          <Link href="/home" className="text-2xl font-black text-[#315d4b] lg:hidden">온기</Link>
          <span className="hidden text-sm text-stone-500 lg:block">당신의 마음이 닿는 곳</span>
          <div className="flex items-center gap-2"><NotificationBell onNew={onNotification} /><Link href="/settings" aria-label="설정" className="rounded-full p-2 text-stone-600 hover:bg-[#e8eee6]"><Settings size={22} /></Link></div>
        </header>
        <details className="border-b border-[#e4e5da] px-5 py-3 lg:hidden">
          <summary className="cursor-pointer text-sm font-bold text-[#315d4b]">메뉴</summary>
          <nav aria-label="모바일 주 메뉴" className="mt-3 space-y-1 pb-2">{navigation}</nav>
        </details>
        <main id="dashboard-content" className="mx-auto max-w-[1348px] px-5 py-6 sm:px-10 sm:py-12">{children}</main>
      </div>
    </div>
  );
}

