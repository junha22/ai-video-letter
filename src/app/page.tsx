"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { api, ApiError, errorText } from "@/lib/api";
import { authDestination, passwordProblem, type AuthConfig, type AuthResult } from "@/lib/auth";
import type { Me } from "@/lib/types";
import { nextOnboardingStep } from "@/lib/useMe";
import { EMPTY_LOGIN_VALUES, LoginOptions, LoginScreen, type LoginMode, type LoginValues } from "@/components/LoginScreen";

export default function Landing() {
  const router = useRouter();
  const [config, setConfig] = useState<AuthConfig | null>(null);
  const [mode, setMode] = useState<LoginMode>("login");
  const [values, setValues] = useState<LoginValues>(EMPTY_LOGIN_VALUES);
  const [busy, setBusy] = useState(false);
  const [devBusy, setDevBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [configError, setConfigError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [retry, setRetry] = useState(0);
  const submitting = useRef(false);
  const request = useRef<AbortController | null>(null);

  const destination = (next: string) => authDestination(next, new URLSearchParams(window.location.search).get("next"));

  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 15000);
    setLoading(true); setConfigError(null);
    const configRequest = api<AuthConfig>("/api/auth/config", { signal: controller.signal })
      .then((data) => { if (active) setConfig(data); })
      .catch((e) => { if (active) setConfigError(controller.signal.aborted ? "연결 시간이 길어지고 있어요. 다시 연결해 주세요." : errorText(e)); });
    const sessionRequest = api<Me>("/api/me", { signal: controller.signal })
      .then((me) => {
        if (active) router.replace(authDestination(nextOnboardingStep(me) || "/home", new URLSearchParams(window.location.search).get("next")));
      })
      .catch((e) => { if (active && !(e instanceof ApiError && e.status === 401) && !controller.signal.aborted) setError("기존 로그인 상태를 확인하지 못했어요. 다시 로그인할 수 있습니다."); });
    Promise.allSettled([configRequest, sessionRequest]).finally(() => { window.clearTimeout(timeout); if (active) setLoading(false); });
    return () => { active = false; controller.abort(); window.clearTimeout(timeout); };
  }, [retry, router]);

  useEffect(() => () => request.current?.abort(), []);

  const submit = async (event: FormEvent, dev = false) => {
    event.preventDefault();
    if (submitting.current || !config || loading) return;
    if (!dev && mode === "signup") {
      const problem = passwordProblem(values.password);
      if (problem) { setError(problem); return; }
      if (values.password !== values.confirmPassword) { setError("비밀번호 확인이 일치하지 않아요."); return; }
      if (!values.name.trim()) { setError("이름을 입력해 주세요."); return; }
    }
    submitting.current = true;
    setError(null);
    if (dev) setDevBusy(true); else setBusy(true);
    const controller = new AbortController();
    request.current = controller;
    const timeout = window.setTimeout(() => controller.abort(), 20000);
    try {
      const path = dev ? "dev-login" : mode === "signup" ? "register" : "login";
      const json = dev ? { name: values.devName.trim() } : { email: values.email.trim(), password: values.password, ...(mode === "signup" ? { name: values.name.trim() } : {}) };
      const result = await api<AuthResult>(`/api/auth/${path}`, { json, signal: controller.signal });
      setValues((old) => ({ ...old, password: "", confirmPassword: "" }));
      router.replace(destination(result.next));
      router.refresh();
    } catch (e) {
      setError(controller.signal.aborted ? "응답을 확인하지 못했어요. 가입했다면 같은 이메일과 비밀번호로 로그인해 주세요." : errorText(e));
    } finally {
      window.clearTimeout(timeout); submitting.current = false; setBusy(false); setDevBusy(false);
    }
  };

  return <LoginScreen><LoginOptions config={config} configLoading={loading} configError={configError} error={error}
    mode={mode} values={values} busy={busy} devBusy={devBusy}
    onModeChange={(next) => { setMode(next); setError(null); setValues((old) => ({ ...old, password: "", confirmPassword: "" })); }}
    onValueChange={(field, value) => setValues((old) => ({ ...old, [field]: value }))}
    onSubmit={(event) => { void submit(event); }} onDevLogin={(event) => { void submit(event, true); }} onRetry={() => setRetry((old) => old + 1)}
  /></LoginScreen>;
}
