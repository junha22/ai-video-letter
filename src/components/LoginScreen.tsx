"use client";

import type { FormEventHandler, ReactNode } from "react";
import { Heart, Mail, MessageCircle, Mic, ShieldCheck } from "lucide-react";
import { FamilyIllustration } from "@/app/home/FamilyIllustration";
import type { AuthConfig } from "@/lib/auth";
import { AuthField, PasswordField } from "./AuthFields";
import { Button, Notice, Spinner } from "./ui";

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

export type LoginMode = "login" | "signup";
export type LoginValues = { name: string; email: string; password: string; confirmPassword: string; devName: string };
export const EMPTY_LOGIN_VALUES: LoginValues = { name: "", email: "", password: "", confirmPassword: "", devName: "" };

/** 실제 화면과 디자인 프리뷰가 공유하는 폼. 인증 요청은 호출자가 처리한다. */
export function LoginOptions({ config, configLoading = false, configError, error, mode, values, busy, devBusy = false, onModeChange, onValueChange, onSubmit, onRetry, onDevLogin }: {
  config: AuthConfig | null;
  configLoading?: boolean;
  configError?: string | null;
  error: string | null;
  mode: LoginMode;
  values: LoginValues;
  busy: boolean;
  devBusy?: boolean;
  onModeChange: (mode: LoginMode) => void;
  onValueChange: (field: keyof LoginValues, value: string) => void;
  onSubmit: FormEventHandler<HTMLFormElement>;
  onRetry: () => void;
  onDevLogin: FormEventHandler<HTMLFormElement>;
}) {
  const pending = busy || devBusy;
  const signup = mode === "signup";
  return (
    <div className="space-y-4">
      <div role="group" aria-label="로그인 또는 회원가입" className="flex rounded-xl bg-[#f1f4ed] p-1">
        {([['login', '로그인'], ['signup', '회원가입']] as const).map(([value, label]) => (
          <button key={value} type="button" disabled={pending} aria-pressed={mode === value} onClick={() => onModeChange(value)} className={`min-h-11 flex-1 rounded-lg px-3 py-2 text-sm font-bold transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#315d4b] ${mode === value ? "bg-white text-[#315d4b] shadow-sm" : "text-[#737d74]"}`}>{label}</button>
        ))}
      </div>
      {configLoading && <div role="status"><Spinner label="로그인 설정을 확인하고 있어요" /></div>}
      {configError && <div role="alert" className="space-y-3"><Notice tone="error">{configError}</Notice><Button type="button" variant="secondary" onClick={onRetry} disabled={pending || configLoading} className="w-full">다시 연결하기</Button></div>}
      {config && !config.password_login && <Notice>이메일 로그인을 사용할 수 없어요. 잠시 후 다시 시도해 주세요.</Notice>}
      <form onSubmit={onSubmit} aria-label={signup ? "회원가입" : "이메일 로그인"} className="space-y-4" aria-busy={busy}>
        <fieldset disabled={pending} className="min-w-0 space-y-4">
          {signup && <AuthField id="signup-name" name="name" label="이름" autoComplete="name" value={values.name} onChange={(event) => onValueChange("name", event.target.value)} required maxLength={50} placeholder="편지를 보내는 분의 이름" />}
          <AuthField id="login-email" name="email" type="email" label="이메일" autoComplete="username" inputMode="email" autoCapitalize="none" spellCheck={false} value={values.email} onChange={(event) => onValueChange("email", event.target.value)} required maxLength={254} placeholder="name@example.com" />
          <PasswordField id="login-password" name="password" label="비밀번호" autoComplete={signup ? "new-password" : "current-password"} value={values.password} onChange={(event) => onValueChange("password", event.target.value)} required hint={signup ? "4자 이상 입력해 주세요." : undefined} />
          {signup && <PasswordField id="signup-confirm-password" name="confirm_password" label="비밀번호 확인" autoComplete="new-password" value={values.confirmPassword} onChange={(event) => onValueChange("confirmPassword", event.target.value)} required />}
        </fieldset>
        {error && <div role="alert"><Notice tone="error">{error}</Notice></div>}
        <Button type="submit" loading={busy} disabled={devBusy || !config?.password_login || configLoading} className="w-full">{signup ? "가입하고 시작하기" : "로그인"}</Button>
      </form>
      <p className="text-center text-xs leading-6 text-[#737d74]">{signup ? "내 계정을 만들고 가족과의 대화를 이어가세요." : "처음 오셨나요? 위의 회원가입을 선택해 주세요."}</p>
      {config?.dev_login && (
        <details className="rounded-2xl border border-dashed border-[#cbd9ce] bg-[#f7f9f4] p-4">
          <summary className="cursor-pointer text-xs font-bold leading-6 text-[#647568]">개발 환경 전용 로그인</summary>
          <p className="mb-3 mt-2 text-xs leading-5 text-[#737d74]">테스트 서버에서만 사용할 수 있는 이름 로그인입니다.</p>
          <form onSubmit={onDevLogin} aria-label="개발용 로그인" className="space-y-3">
            <AuthField id="dev-login-name" name="dev_name" label="테스트 이름" value={values.devName} onChange={(event) => onValueChange("devName", event.target.value)} required maxLength={50} disabled={pending} autoComplete="off" />
            <Button type="submit" variant="secondary" disabled={busy || !values.devName.trim()} loading={devBusy} className="w-full">개발용으로 시작</Button>
          </form>
        </details>
      )}
    </div>
  );
}
