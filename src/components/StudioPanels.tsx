import type { ReactNode } from "react";
import { Camera, Check, Heart, Quote, Sun, User } from "lucide-react";

/** 실제 화면과 디자인 프리뷰에서 공유하는 표시 전용 컴포넌트. */
export function VoiceWorkspace({ reading, controls }: { reading: ReactNode; controls: ReactNode }) {
  return (
    <section className="overflow-hidden rounded-[28px] border border-[#e3e8df] bg-white p-5 shadow-[0_12px_40px_rgba(36,62,44,0.045)] sm:p-8">
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3 border-b border-[#edf0e8] pb-5">
        <div><p className="text-[10px] font-bold tracking-[0.18em] text-[#a77c65]">YOUR VOICE, YOUR HEART</p><h2 className="mt-2 text-xl font-bold tracking-tight text-[#293d31]">익숙한 목소리에 마음을 담아요</h2></div>
        <span className="flex items-center gap-2 rounded-full bg-[#f3f5ed] px-3 py-2 text-xs text-[#607564]"><span className="h-1.5 w-1.5 rounded-full bg-[#7b9c80]" />한 문장씩, 편안하게</span>
      </div>
      <div className="grid gap-5 lg:grid-cols-[1.4fr_0.9fr]">
        <div className="relative flex min-w-0 flex-col justify-center overflow-hidden rounded-[22px] border border-[#e9ece3] bg-[#f8f9f4] p-6 sm:min-h-[330px] sm:p-9">
          <Quote size={84} strokeWidth={1} className="pointer-events-none absolute -right-3 -top-3 rotate-180 text-[#e5ebde]" aria-hidden="true" />
          <div className="relative">{reading}</div>
        </div>
        <div className="flex min-w-0 flex-col items-center justify-center rounded-[22px] bg-[#284f3e] px-6 py-8 text-white sm:px-8">{controls}</div>
      </div>
    </section>
  );
}

export function PhotoGuide() {
  return (
    <section className="overflow-hidden rounded-[28px] border border-[#e3e8df] bg-white shadow-[0_12px_40px_rgba(36,62,44,0.04)]">
      <div className="relative flex items-center justify-center overflow-hidden bg-[#eef2e8] px-6 py-7">
        <span className="absolute right-4 top-4 rounded-full border border-white bg-white/75 px-3 py-1.5 text-[10px] font-semibold tracking-wide text-[#607564]">PHOTO GUIDE</span>
        <svg viewBox="0 0 240 220" role="img" aria-label="밝은 곳에서 정면을 바라보는 사진 가이드" className="h-48 w-56">
          <circle cx="120" cy="104" r="93" fill="#e2e9d9" />
          <rect x="52" y="22" width="136" height="174" rx="30" fill="#fffdf6" />
          <path d="M66 196c1-53 20-73 54-73s53 20 54 73" fill="#8da58a" />
          <ellipse cx="120" cy="87" rx="35" ry="43" fill="#eabea6" />
          <path d="M85 86c-7-39 15-54 37-53 30 1 40 22 32 55-11-8-20-20-24-31-8 16-24 24-45 29" fill="#66554b" />
          <path d="M104 87h6m20 0h6m-25 20q9 7 18 0" fill="none" stroke="#8f6853" strokeLinecap="round" strokeWidth="2.5" />
          <path d="M45 55V29h26m98 0h26v26M45 163v26h26m98 0h26v-26" fill="none" stroke="#648269" strokeWidth="2" strokeLinecap="round" />
          <circle cx="188" cy="167" r="19" fill="#315d4b" />
          <path d="m180 167 6 6 10-12" fill="none" stroke="white" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </div>
      <div className="p-6 sm:p-8">
        <p className="text-[10px] font-bold tracking-[0.16em] text-[#a77c65]">A FACE THEY KNOW</p>
        <h2 className="mb-5 mt-2 text-xl font-bold text-[#293d31]">이런 사진이면 좋아요</h2>
        <ul className="space-y-4">
          {[
            { Icon: User, title: "정면을 바라보는 나", desc: "다른 사람 없이 혼자 나온 사진" },
            { Icon: Camera, title: "얼굴이 충분히 크게", desc: "화면의 3분의 1 이상을 얼굴로 채워 주세요" },
            { Icon: Sun, title: "자연스럽고 선명하게", desc: "밝은 곳에서, 모자·선글라스·마스크 없이" },
          ].map(({ Icon, title, desc }) => <li key={title} className="flex items-start gap-3"><span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-[#f2f5ee] text-[#63816a]"><Icon size={17} aria-hidden="true" /></span><span><strong className="block text-sm font-semibold text-[#3b4c3e]">{title}</strong><span className="mt-1 block text-xs leading-6 text-[#7c8579]">{desc}</span></span></li>)}
        </ul>
      </div>
    </section>
  );
}

export function PhotoPlaceholder() {
  return <div className="flex min-h-[320px] flex-col items-center justify-center rounded-[22px] border border-dashed border-[#bdcdb9] bg-[#f7f8f1] p-6 text-center"><span className="mb-5 flex h-16 w-16 items-center justify-center rounded-[22px] border border-[#e1e8db] bg-white text-[#63816a] shadow-sm"><Camera size={28} strokeWidth={1.5} /></span><p className="text-lg font-semibold tracking-tight text-[#3e5643]">나를 닮은 한 장</p><p className="mt-2 text-xs leading-6 text-[#7b8677]">익숙한 얼굴로 전하는 안부가<br />더 가까이 느껴질 거예요.</p><span className="mt-6 flex items-center gap-1.5 text-[10px] text-[#7b8677]"><Check size={12} /> 밝은 정면 사진을 준비해 주세요</span></div>;
}

export function LetterCompanion({ recipient, example }: { recipient: string; example: string }) {
  return (
    <aside className="relative min-w-0 overflow-hidden rounded-[28px] border border-[#ece4d5] bg-[#f5efe2] p-6 sm:p-8">
      <span className="pointer-events-none absolute -right-16 -top-16 h-48 w-48 rounded-full border-[24px] border-white/30" aria-hidden="true" />
      <p className="relative text-[10px] font-bold tracking-[0.16em] text-[#a17e65]">A LITTLE LETTER, A LOT OF LOVE</p>
      <div className="relative mx-auto my-5 flex h-32 w-40 items-center justify-center" aria-hidden="true"><div className="absolute bottom-1 h-20 w-32 -rotate-6 rounded-xl bg-[#ddcdb6]" /><div className="absolute bottom-5 h-24 w-28 rotate-6 rounded-xl border border-[#e6dfd1] bg-[#fffdf7] shadow-sm"><div className="mx-4 mt-5 h-px bg-[#d9e1d0]" /><div className="mx-4 mt-3 h-px bg-[#d9e1d0]" /><div className="mx-4 mt-3 h-px bg-[#d9e1d0]" /></div><div className="absolute bottom-0 flex h-20 w-36 items-center justify-center rounded-xl bg-[#e9ddc7] shadow-sm"><Heart size={24} strokeWidth={1.5} className="text-[#9a7960]" /></div></div>
      <h2 className="relative text-xl font-bold leading-relaxed tracking-tight text-[#4b4d3b]">{recipient}께 전할<br />오늘의 작은 마음</h2>
      <p className="mt-3 text-xs leading-7 text-[#8b8674]">거창한 이야기가 아니어도 좋아요.<br />평소 말하듯 한 줄이면 충분해요.</p>
      <div className="mt-6 rounded-2xl border border-white/70 bg-white/65 p-5"><p className="mb-3 text-[10px] font-semibold text-[#9a8b75]">이렇게 시작해 보세요</p><blockquote className="break-words text-sm leading-8 text-[#66694f]">“{example}”</blockquote></div>
      <p className="mt-5 flex items-start gap-2 text-[11px] leading-6 text-[#8c8777]"><Check size={14} className="mt-1 shrink-0" />대본은 다음 화면에서 직접 확인하고 고칠 수 있어요.</p>
    </aside>
  );
}
