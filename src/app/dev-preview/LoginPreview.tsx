"use client";

import { useState } from "react";
import { EMPTY_LOGIN_VALUES, LoginOptions, LoginScreen, type LoginMode } from "@/components/LoginScreen";

export function LoginPreview() {
  const [state, setState] = useState("ready");
  const [mode, setMode] = useState<LoginMode>("login");
  const [values, setValues] = useState(EMPTY_LOGIN_VALUES);
  const [notice, setNotice] = useState("");
  const sample = () => setNotice("샘플 화면입니다. 계정 생성이나 실제 로그인 요청은 보내지 않았습니다.");
  return <>
    <div className="mb-5 flex flex-wrap items-center gap-3 rounded-2xl border border-[#dce9db] bg-[#e9f0e9] p-4 text-sm text-[#315d4b]">
      <label htmlFor="login-preview-state" className="font-bold">로그인 샘플 상태</label><select id="login-preview-state" value={state} onChange={(event) => { setState(event.target.value); setNotice(""); }} className="min-h-11 rounded-xl border border-[#cbd9ce] bg-white px-3 py-2"><option value="ready">이메일 로그인·회원가입</option><option value="loading">로그인 설정 확인 중</option><option value="error">서버 연결 실패</option></select><span className="text-xs leading-6">모든 상태는 샘플이며 실제 로그인은 하지 않습니다.</span>
    </div>
    <LoginScreen preview><LoginOptions config={state === "ready" ? { password_login: true, dev_login: false, password_min_length: 4, password_max_length: null } : null} configLoading={state === "loading"} configError={state === "error" ? "서버에 연결할 수 없어요." : null} error={null} mode={mode} values={values} busy={false} onModeChange={setMode} onValueChange={(field, value) => setValues((old) => ({ ...old, [field]: value }))} onSubmit={(event) => { event.preventDefault(); sample(); }} onDevLogin={(event) => { event.preventDefault(); sample(); }} onRetry={sample} /></LoginScreen>
    <p role="status" aria-live="polite" className="mt-4 text-center text-sm leading-7 text-[#315d4b]">{notice}</p>
  </>;
}
