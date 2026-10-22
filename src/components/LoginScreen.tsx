"use client";

import type { ChangeEventHandler, KeyboardEventHandler, ReactNode } from "react";
import { Heart, Mail, MessageCircle, Mic, ShieldCheck } from "lucide-react";
import { FamilyIllustration } from "@/app/home/FamilyIllustration";
import { Button, Notice, Spinner } from "./ui";

export const KAKAO_LOGIN_CLASS = "flex min-h-14 w-full items-center justify-center gap-2 rounded-2xl bg-[#FEE500] px-4 py-4 text-base font-bold text-[#191919] transition-colors hover:bg-[#f5dc00] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-[#315d4b]";

/** 인증과 API를 소유하지 않는 공통 화면. 실제 페이지와 프리뷰가 같은 UI를 사용한다. */
export function LoginScreen({ children, preview = false }: { children: ReactNode; preview?: boolean }) {
  return (
    <div className={`bg-[#f8f7f2] text-[#2e342f] tracking-[-0.035em] ${preview ? "rounded-[28px] border border-[#e8e9e2]" : "min-h-screen"}`}>
      <div className="mx-auto max-w-6xl px-5 py-7 sm:px-8 sm:py-10 lg:px-12 lg:py-12">
        <header className="mb-7 flex flex-wrap items-center justify-between gap-3 lg:mb-10">
          <p className="flex items-center gap-2.5 text-[28px] font-black tracking-tight text-[#315d4b]"><span className="flex h-9 w-9 -rotate-6 items-center justify-center rounded-xl bg-[#315d4b] text-white"><Heart size={21} aria-hidden="true" /></span>온기</p>
          <p className="text-xs text-[#737d74]">{preview ? "로그인 디자인 프리뷰 · 샘플 데이터" : "마음을 잇는 영상 편지"}</p>
        </header>
        <div className="grid items-center gap-7 lg:grid-cols-[1.1fr_1fr] lg:gap-12">
          <section aria-labelledby="login-brand-title" className="min-w-0">
            <p className="hidden text-[11px] font-bold tracking-[0.16em] text-[#b77560] lg:block">A LITTLE CLOSER, EVERY DAY</p>
            <h1 id="login-brand-title" className="text-[32px] font-extrabold leading-snug tracking-tighter sm:text-4xl lg:mt-3 lg:text-[44px]">멀리 있어도,<br /><span className="text-[#42735d]">마음은 가까이.</span></h1>
            <p className="mt-3 max-w-sm text-sm leading-7 text-[#6e786e] sm:text-base">익숙한 얼굴과 목소리로 부모님께<br className="hidden sm:block" /> 오늘의 마음을 전하세요.</p>
            <div className="mt-7 hidden overflow-hidden rounded-[28px] bg-[#f4eadb] shadow-[0_18px_48px_rgba(52,67,52,0.08)] lg:block"><FamilyIllustration /></div>
          </section>
          <section aria-labelledby="login-card-title" className="min-w-0 rounded-[28px] border border-[#e8e9e2] bg-white p-6 shadow-[0_18px_48px_rgba(52,67,52,0.06)] sm:p-8 lg:p-9">
            <span className="mb-5 flex h-12 w-12 items-center justify-center rounded-2xl bg-[#e9f0e9] text-[#315d4b]"><Mail size={24} aria-hidden="true" /></span>
            <h2 id="login-card-title" className="text-[28px] font-extrabold tracking-tight">반가워요!</h2>
            <p className="mb-7 mt-2 text-sm leading-7 text-[#737d74]">소중한 사람에게 전하고 싶은 한마디,<br />온기와 함께 영상 편지로 담아 보세요.</p>
            {children}
            <p className="mt-6 flex items-start gap-2 border-t border-[#edf0e9] pt-5 text-xs leading-6 text-[#737d74]"><ShieldCheck size={17} className="mt-1 shrink-0 text-[#60896c]" aria-hidden="true" />목소리와 얼굴 사용 동의를 확인하고,<br />완성된 영상은 직접 확인한 뒤 전해요.</p>
          </section>
        </div>
        <footer className="mt-8 flex flex-wrap justify-center gap-x-6 gap-y-2 text-xs leading-6 text-[#737d74] lg:mt-10">
          <span className="flex items-center gap-2"><Mic size={15} aria-hidden="true" />익숙한 목소리로</span><span className="flex items-center gap-2"><MessageCircle size={15} aria-hidden="true" />다정한 한마디를</span><span className="flex items-center gap-2"><Heart size={15} aria-hidden="true" />가족에게 가까이</span>
        </footer>
      </div>
    </div>
  );
}

/** 표시 조건·입력값·이벤트는 호출자가 제공한다. 여기에서는 로그인 요청을 만들지 않는다. */
export function LoginOptions({ config, error, name, busy, kakaoAction, onNameChange, onNameKeyDown, onDevLogin }: {
  config: { kakao: boolean; dev_login: boolean } | null;
  error: string | null;
  name: string;
  busy: boolean;
  kakaoAction: ReactNode;
  onNameChange: ChangeEventHandler<HTMLInputElement>;
  onNameKeyDown: KeyboardEventHandler<HTMLInputElement>;
  onDevLogin: () => void | Promise<void>;
}) {
  return (
    <div className="space-y-4">
      {error && <div role="alert"><Notice tone="error">{error}</Notice></div>}
      {!config && !error && <div role="status"><Spinner label="로그인 정보를 확인하고 있어요" /></div>}
      {config?.kakao && kakaoAction}
      {config?.dev_login && (
        <div className="rounded-2xl border border-dashed border-[#cbd9ce] bg-[#f7f9f4] p-4">
          <label htmlFor="login-name" className="mb-3 block text-xs font-bold leading-6 text-[#647568]">개발용 로그인 (카카오 키 설정 전)</label>
          <div className="flex gap-2">
            <input id="login-name" value={name} onChange={onNameChange} onKeyDown={onNameKeyDown} placeholder="내 이름 (예: 준하)" maxLength={20} className="min-h-12 min-w-0 flex-1 rounded-xl border border-[#d6dfd2] bg-white px-3 py-3 text-base outline-none focus:border-[#315d4b] focus:ring-2 focus:ring-[#dce8d8]" />
            <Button onClick={onDevLogin} disabled={!name.trim()} loading={busy} className="min-h-12 shrink-0 !rounded-xl !bg-[#315d4b] !px-4 !text-white hover:!bg-[#234b39] disabled:!bg-stone-200 disabled:!text-stone-500">시작</Button>
          </div>
        </div>
      )}
    </div>
  );
}
