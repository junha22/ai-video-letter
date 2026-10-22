"use client";

import Link from "next/link";
import { ChevronLeft, Settings } from "lucide-react";
import type { ReactNode } from "react";
import { NotificationBell } from "./Notifications";
import type { NotificationItem } from "@/lib/types";

/** 로그인한 자녀용 화면 틀 */
export function AppShell({
  children,
  back,
  onNotification,
}: {
  children: ReactNode;
  back?: string;
  onNotification?: (n: NotificationItem) => void;
}) {
  return (
    <div className="mx-auto min-h-screen max-w-md bg-[#FAF7F2]">
      <header className="sticky top-0 z-30 flex items-center justify-between border-b border-stone-200/70 bg-[#FAF7F2]/95 px-3 py-2 backdrop-blur">
        <div className="flex items-center gap-1">
          {back && (
            <Link href={back} className="rounded-full p-2 text-stone-700 hover:bg-stone-100" aria-label="뒤로">
              <ChevronLeft className="h-6 w-6" />
            </Link>
          )}
          <Link href="/home" className="px-2 text-xl font-black tracking-tight text-ongi-800">
            온기
          </Link>
        </div>
        <div className="flex items-center">
          <NotificationBell onNew={onNotification} />
          <Link href="/settings" className="rounded-full p-2 text-stone-700 hover:bg-stone-100" aria-label="설정">
            <Settings className="h-6 w-6" />
          </Link>
        </div>
      </header>
      <main className="px-4 pb-16 pt-5">{children}</main>
    </div>
  );
}
