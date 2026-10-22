"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api, errorText } from "@/lib/api";
import { KAKAO_LOGIN_CLASS, LoginOptions, LoginScreen } from "@/components/LoginScreen";

type AuthConfig = { kakao: boolean; dev_login: boolean };

export default function Landing() {
  const router = useRouter();
  const [config, setConfig] = useState<AuthConfig | null>(null);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (new URLSearchParams(window.location.search).get("login_error")) {
      setError("카카오 로그인에 실패했어요. 다시 시도해 주세요.");
    }
    api("/api/me")
      .then(() => router.replace("/home"))
      .catch(() => api<AuthConfig>("/api/auth/config").then(setConfig).catch(() => setError("서버에 연결할 수 없어요.")));
  }, [router]);

  const devLogin = async () => {
    setBusy(true);
    setError(null);
    try {
      await api("/api/auth/dev-login", { json: { name: name.trim() } });
      router.replace("/home");
    } catch (e) {
      setError(errorText(e));
      setBusy(false);
    }
  };

  return (
    <LoginScreen>
      <LoginOptions
        config={config}
        error={error}
        name={name}
        busy={busy}
        kakaoAction={<a href="/api/auth/kakao/login" className={KAKAO_LOGIN_CLASS}>카카오로 시작하기</a>}
        onNameChange={(e) => setName(e.target.value)}
        onNameKeyDown={(e) => e.key === "Enter" && name.trim() && devLogin()}
        onDevLogin={devLogin}
      />
    </LoginScreen>
  );
}
