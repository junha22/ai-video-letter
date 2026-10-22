"use client";

import { useState } from "react";
import { KAKAO_LOGIN_CLASS, LoginOptions, LoginScreen } from "@/components/LoginScreen";

export function LoginPreview() {
  const [state, setState] = useState("ready");
  const [name, setName] = useState("");
  const [notice, setNotice] = useState("");

  const sampleLogin = () => setNotice("샘플 버튼입니다. 인증 요청·세션 생성·화면 이동은 수행하지 않았습니다.");

  return (
    <>
      <div className="mb-5 flex flex-wrap items-center gap-3 rounded-2xl border border-[#dce9db] bg-[#e9f0e9] p-4 text-sm text-[#315d4b]">
        <label htmlFor="login-preview-state" className="font-bold">로그인 샘플 상태</label>
        <select id="login-preview-state" value={state} onChange={(event) => { setState(event.target.value); setNotice(""); }} className="min-h-11 rounded-xl border border-[#cbd9ce] bg-white px-3 py-2">
          <option value="ready">카카오·개발용 로그인 표시</option>
          <option value="loading">로그인 설정 확인 중</option>
          <option value="error">서버 연결 실패</option>
        </select>
        <span className="text-xs leading-6">모든 상태는 샘플이며 실제 로그인은 하지 않습니다.</span>
      </div>
      <LoginScreen preview>
        <LoginOptions
          config={state === "ready" ? { kakao: true, dev_login: true } : null}
          error={state === "error" ? "서버에 연결할 수 없어요." : null}
          name={name}
          busy={false}
          kakaoAction={<button type="button" onClick={sampleLogin} className={KAKAO_LOGIN_CLASS}>카카오로 시작하기</button>}
          onNameChange={(event) => setName(event.target.value)}
          onNameKeyDown={(event) => { if (event.key === "Enter" && name.trim()) sampleLogin(); }}
          onDevLogin={sampleLogin}
        />
      </LoginScreen>
      <p role="status" aria-live="polite" className="mt-4 text-center text-sm leading-7 text-[#315d4b]">{notice}</p>
    </>
  );
}
