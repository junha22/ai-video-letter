"use client";
import Link from "next/link";
import { Heart } from "lucide-react";
import type { ReactNode } from "react";
export function AlbumFrame({children,navigation,actions,onHome,preview=false,back,banner}:{children:ReactNode;navigation:ReactNode;actions?:ReactNode;onHome?:()=>void;preview?:boolean;back?:ReactNode;banner?:ReactNode}) {
 const brand=<><span className="album-brand-mark"><Heart size={21} strokeWidth={1.8}/></span><span>온기<small>가족의 마음을 모으다</small></span></>;
 return <div className={`album-app ${preview?"concept new-preview":""}`}><a href="#album-content" className="album-skip">본문으로 이동</a>{preview&&<div className="album-preview-ribbon"><strong>DESIGN PREVIEW · 가족 앨범 × 온기 클럽</strong><span>샘플 데이터 · 실제 녹음·생성·발송 없음</span></div>}<header className="album-header">{onHome?<button className="album-brand" onClick={onHome} aria-label="앨범 첫 화면으로">{brand}</button>:<Link className="album-brand" href="/home" aria-label="앨범 첫 화면으로">{brand}</Link>}<nav className="album-navigation" aria-label={preview?"프리뷰 앨범 메뉴":"앨범 메뉴"}>{navigation}</nav><div className="album-header-actions">{actions}</div></header>{banner}<main id="album-content" className="album-main">{back&&<div className="album-back">{back}</div>}{children}</main><footer className="album-footer"><span>♥ 온기 · YOUR FAMILY, A LITTLE CLOSER.</span><span>{preview?"인물·편지·상태는 샘플입니다. 새로고침하면 초기화돼요.":"함께 쌓아 가는, 우리 가족의 다정한 기록."}</span></footer></div>;
}
