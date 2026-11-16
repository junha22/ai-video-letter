"use client";
import Link from "next/link";
import { AlertTriangle, ChevronLeft, PenLine, Settings } from "lucide-react";
import { usePathname } from "next/navigation";
import { useState, type ReactNode } from "react";
import { api } from "@/lib/api";
import type { NotificationItem } from "@/lib/types";
import { NotificationBell } from "./Notifications";
import { AlbumFrame } from "./album/AlbumFrame";
export function DashboardShell({children,back,onNotification}:{children:ReactNode;back?:string;onNotification?:(n:NotificationItem)=>void}){
 const pathname=usePathname();
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
 const navigation=<><Link href="/home" aria-current={pathname==="/home"?"page":undefined}>우리의 앨범</Link><Link href="/letters" aria-current={pathname==="/letters"||pathname.startsWith("/conversations/")?"page":undefined}>가족 편지함</Link><Link href="/onboarding/voice" aria-current={pathname.startsWith("/onboarding/")?"page":undefined}>편지를 위한 준비</Link></>;
 const actions=<><NotificationBell onNew={onNotification} onItems={onItems}/><Link className="album-icon-button" href="/settings" aria-label="나의 설정"><Settings size={20}/></Link><Link className="album-write" href="/messages/new"><PenLine size={15}/><span>새 편지</span></Link></>;
 return <AlbumFrame banner={alerts.length > 0 && <div role="alert" className="border-b border-[#8f2a18] bg-[#A8321E] px-5 py-3 text-white sm:px-10">
          {alerts.slice(0, 3).map((n) => <div key={n.id} className="flex flex-wrap items-center gap-x-4 gap-y-2 py-1">
            <p className="flex min-w-0 flex-1 items-center gap-2 text-sm font-bold"><AlertTriangle size={18} className="shrink-0" />{n.text}</p>
            <div className="flex gap-2">{n.recipient_id && <Link href={`/conversations/${n.recipient_id}`} onClick={() => confirmAlert(n.id)} className="rounded-full bg-white px-3 py-1.5 text-xs font-bold text-[#A8321E]">대화방에서 보기</Link>}<button type="button" onClick={() => confirmAlert(n.id)} className="rounded-full border border-white/70 px-3 py-1.5 text-xs font-bold">확인했어요</button></div>
          </div>)}
        </div>} navigation={navigation} actions={actions} back={back?<Link href={back}><ChevronLeft size={17}/>이전 화면</Link>:undefined}>{children}</AlbumFrame>;
}
