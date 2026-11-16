"use client";
import Link from "next/link";
import { ChevronLeft, PenLine, Settings } from "lucide-react";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import type { NotificationItem } from "@/lib/types";
import { NotificationBell } from "./Notifications";
import { AlbumFrame } from "./album/AlbumFrame";
export function DashboardShell({children,back,onNotification}:{children:ReactNode;back?:string;onNotification?:(n:NotificationItem)=>void}){
 const pathname=usePathname();
 const navigation=<><Link href="/home" aria-current={pathname==="/home"?"page":undefined}>우리의 앨범</Link><Link href="/letters" aria-current={pathname==="/letters"||pathname.startsWith("/conversations/")?"page":undefined}>가족 편지함</Link><Link href="/onboarding/voice" aria-current={pathname.startsWith("/onboarding/")?"page":undefined}>편지를 위한 준비</Link></>;
 const actions=<><NotificationBell onNew={onNotification}/><Link className="album-icon-button" href="/settings" aria-label="나의 설정"><Settings size={20}/></Link><Link className="album-write" href="/messages/new"><PenLine size={15}/><span>새 편지</span></Link></>;
 return <AlbumFrame navigation={navigation} actions={actions} back={back?<Link href={back}><ChevronLeft size={17}/>이전 화면</Link>:undefined}>{children}</AlbumFrame>;
}
