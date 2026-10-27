"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { KeyRound } from "lucide-react";
import { api, errorText } from "@/lib/api";
import { passwordProblem, type AuthResult } from "@/lib/auth";
import type { Me } from "@/lib/types";
import { AuthField, PasswordField } from "./AuthFields";
import { Button, Card, Notice } from "./ui";

export function AccountSecurity({ user, disabled, onBusyChange, onSaved }: {
  user: Me["user"];
  disabled: boolean;
  onBusyChange: (busy: boolean) => void;
  onSaved: () => Promise<unknown>;
}) {
  const hasPassword = Boolean(user.has_password);
  const [email, setEmail] = useState("");
  const [current, setCurrent] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState("");
  const submitting = useRef(false);
  const controller = useRef<AbortController | null>(null);
  useEffect(() => () => controller.current?.abort(), []);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (submitting.current || disabled) return;
    setNotice("");
    const problem = passwordProblem(password);
    if (problem) { setError(problem); return; }
    if (password !== confirm) { setError("비밀번호 확인이 일치하지 않아요."); return; }
    submitting.current = true; setBusy(true); onBusyChange(true); setError(null);
    const request = new AbortController(); controller.current = request;
    const timeout = window.setTimeout(() => request.abort(), 20000);
    try {
      await api<AuthResult>(hasPassword ? "/api/auth/password" : "/api/auth/credentials", {
        json: hasPassword ? { current_password: current, new_password: password } : { email: email.trim(), password }, signal: request.signal,
      });
      setCurrent(""); setPassword(""); setConfirm(""); setEmail("");
      await onSaved();
      setNotice(hasPassword ? "비밀번호를 변경했어요. 다른 기기의 기존 로그인은 해제됩니다." : "이메일을 연결했어요. 다음부터 이메일과 비밀번호로 로그인해 주세요.");
    } catch (e) {
      setError(request.signal.aborted ? "처리 결과를 확인하지 못했어요. 다시 로그인해 변경 여부를 확인해 주세요." : errorText(e));
    } finally {
      window.clearTimeout(timeout); submitting.current = false; setBusy(false); onBusyChange(false);
    }
  };

  return <Card className="!rounded-[28px] p-5 sm:p-7">
    <h2 className="flex items-center gap-2 text-lg font-bold text-[#315d4b]"><KeyRound size={21} />{hasPassword ? "비밀번호 변경" : "이메일 로그인 연결"}</h2>
    <p className="mb-6 mt-3 text-sm leading-7 text-stone-500">{hasPassword ? "4자 이상의 새 비밀번호를 설정해 주세요. 변경하면 다른 기기의 로그인도 해제돼요." : "현재 계정의 영상과 대화를 그대로 유지하면서 이메일과 비밀번호로 로그인할 수 있어요."}</p>
    <form onSubmit={submit} aria-label={hasPassword ? "비밀번호 변경" : "이메일 연결"} className="space-y-4">
      <fieldset disabled={busy || disabled} className="min-w-0 space-y-4">
        {hasPassword ? <PasswordField id="account-current-password" label="현재 비밀번호" name="current_password" value={current} onChange={(e) => setCurrent(e.target.value)} autoComplete="current-password" required /> : <AuthField id="account-email" label="연결할 이메일" name="email" value={email} onChange={(e) => setEmail(e.target.value)} type="email" autoComplete="username" autoCapitalize="none" spellCheck={false} required maxLength={254} />}
        <PasswordField id="account-new-password" label={hasPassword ? "새 비밀번호" : "비밀번호"} name="new_password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="new-password" required hint="4자 이상 입력해 주세요." />
        <PasswordField id="account-confirm-password" label="비밀번호 확인" name="confirm_password" value={confirm} onChange={(e) => setConfirm(e.target.value)} autoComplete="new-password" required />
      </fieldset>
      {error && <div role="alert"><Notice tone="error">{error}</Notice></div>}
      {notice && <div role="status"><Notice tone="success">{notice}</Notice></div>}
      <Button type="submit" loading={busy} disabled={disabled} className="w-full">{hasPassword ? "비밀번호 변경하기" : "이메일 연결하기"}</Button>
    </form>
  </Card>;
}
