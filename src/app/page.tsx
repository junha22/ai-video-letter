"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Heart, Mic, Send, Sparkles } from "lucide-react";
import { api, errorText } from "@/lib/api";
import { Button, Notice } from "@/components/ui";

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
    <div className="mx-auto flex min-h-screen max-w-md flex-col px-6 py-12">
      <div className="flex-1">
        <p className="text-4xl font-black tracking-tight text-ongi-800">온기</p>
        <h1 className="mt-6 text-[28px] font-extrabold leading-snug text-stone-900">
          한 줄만 쓰면,
          <br />
          내 목소리와 얼굴로
          <br />
          부모님께 영상 편지가 가요
        </h1>

        <ul className="mt-10 space-y-4 text-[17px] text-stone-700">
          <li className="flex items-start gap-3">
            <Mic className="mt-0.5 h-6 w-6 shrink-0 text-ongi-700" />
            <span>처음 한 번, 3분 동안 문장을 읽어 목소리를 등록해요</span>
          </li>
          <li className="flex items-start gap-3">
            <Sparkles className="mt-0.5 h-6 w-6 shrink-0 text-ongi-700" />
            <span>&ldquo;오늘 비 온대 우산 챙겨&rdquo; 한 줄이면 AI가 15초 대본으로 다듬어요</span>
          </li>
          <li className="flex items-start gap-3">
            <Send className="mt-0.5 h-6 w-6 shrink-0 text-ongi-700" />
            <span>미리 보고 승인하면 카카오톡 링크로 보내고, 보셨는지 알려 드려요</span>
          </li>
          <li className="flex items-start gap-3">
            <Heart className="mt-0.5 h-6 w-6 shrink-0 text-ongi-700" />
            <span>부모님은 링크를 누르고 재생 버튼 한 번만 누르면 돼요</span>
          </li>
        </ul>
      </div>

      <div className="mt-10 space-y-3">
        {error && <Notice tone="error">{error}</Notice>}
        {config?.kakao && (
          <a
            href="/api/auth/kakao/login"
            className="flex w-full items-center justify-center gap-2 rounded-2xl bg-[#FEE500] py-4 text-[17px] font-bold text-[#191919]"
          >
            카카오로 시작하기
          </a>
        )}
        {config?.dev_login && (
          <div className="rounded-2xl border border-dashed border-stone-300 p-4">
            <p className="mb-2 text-sm font-semibold text-stone-600">개발용 로그인 (카카오 키 설정 전)</p>
            <div className="flex gap-2">
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && name.trim() && devLogin()}
                placeholder="내 이름 (예: 준하)"
                maxLength={20}
                className="min-w-0 flex-1 rounded-xl border border-stone-300 bg-white px-4 py-3 text-base outline-none focus:border-ongi-600"
              />
              <Button onClick={devLogin} disabled={!name.trim()} loading={busy} className="shrink-0">
                시작
              </Button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
