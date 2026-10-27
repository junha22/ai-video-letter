"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ChevronRight, LogOut, Trash2 } from "lucide-react";
import { api, errorText } from "@/lib/api";
import { useMe } from "@/lib/useMe";
import { AppShell } from "@/components/AppShell";
import { AccountSecurity } from "@/components/AccountSecurity";
import { Button, Card, Notice, Spinner } from "@/components/ui";

export default function SettingsPage() {
  const router = useRouter();
  const { me, reload } = useMe();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [logoutBusy, setLogoutBusy] = useState(false);
  const [authBusy, setAuthBusy] = useState(false);

  const logout = async () => {
    if (logoutBusy || busy || authBusy) return;
    setLogoutBusy(true); setError(null);
    try {
      await api("/api/auth/logout", { method: "POST" });
      router.replace("/"); router.refresh();
    } catch (e) { setError(errorText(e)); setLogoutBusy(false); }
  };

  const withdraw = async () => {
    if (
      !confirm(
        "동의를 철회하면 녹음, 목소리 모델, 사진, 만든 영상이 모두 지워지고 보낸 링크도 더 이상 열리지 않아요. 되돌릴 수 없어요. 철회할까요?",
      )
    )
      return;
    setBusy(true);
    setError(null);
    try {
      await api("/api/consent/withdraw", { method: "POST" });
      router.replace("/onboarding/consent");
    } catch (e) {
      setError(errorText(e));
      setBusy(false);
    }
  };

  if (!me) {
    return (
      <AppShell back="/home">
        <Spinner />
      </AppShell>
    );
  }

  const links = [
    { href: "/onboarding/parent", label: "부모님 정보 고치기" },
    { href: "/onboarding/voice", label: "목소리 다시 등록하기" },
    { href: "/onboarding/photo", label: "얼굴 사진 바꾸기" },
  ];

  return (
    <AppShell back="/home">
      <p className="text-[10px] font-bold tracking-[0.16em] text-[#a77c65]">MY LITTLE SPACE</p>
      <h1 className="mt-3 text-[27px] font-bold tracking-tighter text-[#2b3d30] sm:text-[34px]">나의 설정</h1>
      <p className="mb-8 mt-3 text-sm leading-7 text-[#7c8775]">나와 가족의 연결을 관리해요.</p>
      {error && <div className="mb-5" role="alert"><Notice tone="error">{error}</Notice></div>}
      <div className="grid items-start gap-6 lg:grid-cols-2">
      <Card className="!rounded-[28px] p-5 sm:p-7">
        <p className="px-3 pb-1 pt-2 text-sm text-stone-500">
          {me.user.name} · {me.user.has_password ? "이메일 로그인" : me.user.kakao ? "카카오 로그인" : "개발용 로그인"}
        </p>
        {me.user.email && <p className="break-all px-3 pb-3 pt-1 text-sm font-semibold text-[#315d4b]">{me.user.email}</p>}
        {me.consent_ok &&
          links.map((l) => (
            <Link key={l.href} href={l.href} className="flex items-center justify-between rounded-xl px-3 py-3.5 hover:bg-stone-50">
              <span className="font-semibold text-stone-800">{l.label}</span>
              <ChevronRight className="h-5 w-5 text-stone-400" />
            </Link>
          ))}
        <button onClick={logout} disabled={logoutBusy || busy || authBusy} className="flex w-full items-center gap-2 rounded-xl px-3 py-3.5 text-left font-semibold text-stone-800 hover:bg-stone-50 disabled:opacity-50">
          <LogOut className="h-5 w-5" /> {logoutBusy ? "로그아웃 중…" : "로그아웃"}
        </button>
      </Card>
      <AccountSecurity user={me.user} disabled={busy || logoutBusy} onBusyChange={setAuthBusy} onSaved={reload} />

      {me.consent_ok && (
        <Card className="border-red-200">
          <p className="font-bold text-stone-900">동의 철회</p>
          <p className="mt-1 text-sm leading-relaxed text-stone-600">
            녹음, 목소리 모델, 사진, 만든 영상을 모두 지우고 보낸 링크를 막아요. 다시 쓰려면 처음부터 등록해야 해요.
          </p>
          <Button variant="danger" onClick={withdraw} loading={busy} disabled={logoutBusy || authBusy} className="mt-4 w-full">
            <Trash2 className="h-5 w-5" /> 동의 철회하고 모두 삭제
          </Button>
        </Card>
      )}
      </div>
    </AppShell>
  );
}
