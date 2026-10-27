"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { Bell, X } from "lucide-react";
import { api } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { kstDate } from "@/lib/conversations";
import type { NotificationItem } from "@/lib/types";

const POLL_MS = 10_000;

/** 헤더의 알림 벨. 주기적으로 확인해서 새 알림이 오면 화면 위에 띄우고, 허용했다면 브라우저 알림도 보낸다. */
export function NotificationBell({ onNew }: { onNew?: (n: NotificationItem) => void }) {
  const [items, setItems] = useState<NotificationItem[]>([]);
  const [unread, setUnread] = useState(0);
  const [open, setOpen] = useState(false);
  const [toast, setToast] = useState<NotificationItem | null>(null);
  const [permission, setPermission] = useState<NotificationPermission | "unsupported">("default");
  const lastSeen = useRef<number | null>(null);
  const onNewRef = useRef(onNew);
  onNewRef.current = onNew;

  const load = useCallback(async () => {
    try {
      const data = await api<{ unread: number; items: NotificationItem[] }>("/api/notifications");
      setItems(data.items);
      setUnread(data.unread);
      const newest = data.items[0];
      if (lastSeen.current !== null && newest && newest.id > lastSeen.current && !newest.read) {
        setToast(newest);
        onNewRef.current?.(newest);
        if ("Notification" in window && Notification.permission === "granted") {
          new Notification("온기", { body: newest.text });
        }
      }
      lastSeen.current = newest?.id ?? 0;
    } catch {
      // 로그아웃 상태 등은 조용히 넘어간다
    }
  }, []);

  useEffect(() => {
    setPermission("Notification" in window ? Notification.permission : "unsupported");
    load();
    const timer = window.setInterval(load, POLL_MS);
    return () => window.clearInterval(timer);
  }, [load]);

  useEffect(() => {
    if (!toast) return;
    const t = window.setTimeout(() => setToast(null), 5000);
    return () => window.clearTimeout(t);
  }, [toast]);

  const toggle = async () => {
    setOpen(!open);
    if (!open && unread) {
      await api("/api/notifications/read", { method: "POST" });
      setUnread(0);
    }
  };

  return (
    <>
      <button onClick={toggle} className="relative rounded-full p-2 text-stone-700 hover:bg-stone-100" aria-label="알림">
        <Bell className="h-6 w-6" />
        {unread > 0 && (
          <span className="absolute right-1 top-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-red-600 px-1 text-[10px] font-bold text-white">
            {unread}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute right-3 top-14 z-40 w-[min(22rem,calc(100vw-1.5rem))] rounded-2xl border border-stone-200 bg-white p-2 shadow-xl">
          {permission === "default" && (
            <button
              onClick={async () => setPermission(await Notification.requestPermission())}
              className="mb-1 w-full rounded-xl bg-amber-50 px-3 py-2 text-left text-sm font-semibold text-amber-900"
            >
              브라우저 알림 켜기 — 부모님이 영상을 보시면 바로 알려 드려요
            </button>
          )}
          {items.length === 0 ? (
            <p className="px-3 py-6 text-center text-sm text-stone-500">아직 알림이 없어요</p>
          ) : (
            <ul className="max-h-80 overflow-y-auto">
              {items.map((n) => (
                <li key={n.id}>
                  <Link
                    href={n.recipient_id ? `/conversations/${n.recipient_id}?date=${kstDate(new Date(n.created_at))}` : n.message_id ? `/messages/${n.message_id}` : "/home"}
                    onClick={() => setOpen(false)}
                    className="block rounded-xl px-3 py-2.5 hover:bg-stone-50"
                  >
                    <p className={`text-[15px] ${n.read ? "text-stone-600" : "font-bold text-stone-900"}`}>{n.text}</p>
                    <p className="text-xs text-stone-400">{formatDate(n.created_at)}</p>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {toast && (
        <div className="fixed inset-x-0 top-3 z-50 flex justify-center px-4">
          <div className="flex w-full max-w-md items-center gap-3 rounded-2xl bg-stone-900 px-4 py-3 text-white shadow-2xl">
            <Bell className="h-5 w-5 shrink-0 text-amber-300" />
            <p className="flex-1 text-[15px] font-semibold">{toast.text}</p>
            <button onClick={() => setToast(null)} aria-label="닫기">
              <X className="h-5 w-5 text-stone-400" />
            </button>
          </div>
        </div>
      )}
    </>
  );
}
