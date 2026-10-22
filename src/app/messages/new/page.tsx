"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Sparkles } from "lucide-react";
import { api, errorText } from "@/lib/api";
import type { Message } from "@/lib/types";
import { useMe } from "@/lib/useMe";
import { AppShell } from "@/components/AppShell";
import { LetterCompanion } from "@/components/StudioPanels";
import { Button, Notice, Spinner } from "@/components/ui";

const TEMPLATES = [
  { key: "greeting", label: "안부", example: "요즘 바빠서 연락 못 했어 미안 밥 잘 챙겨 먹어" },
  { key: "weather", label: "날씨", example: "오늘 비 온대 우산 챙겨" },
  { key: "hospital", label: "병원 일정", example: "목요일 10시 정형외과 예약했어 같이 가자" },
  { key: "birthday", label: "생일", example: "생신 축하해 주말에 케이크 사 갈게" },
  { key: "holiday", label: "명절", example: "추석에 금요일 저녁에 내려갈게" },
];

export default function NewMessagePage() {
  const router = useRouter();
  const { me } = useMe();
  const [template, setTemplate] = useState("greeting");
  const [memo, setMemo] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (me && !me.can_write) router.replace("/home");
  }, [me, router]);

  const current = TEMPLATES.find((t) => t.key === template)!;

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const m = await api<Message>("/api/messages", { json: { memo: memo.trim(), template } });
      router.push(`/messages/${m.id}`);
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

  return (
    <AppShell back="/home">
      <p className="text-[10px] font-bold tracking-[0.16em] text-[#a77c65]">WRITE YOUR HEART</p>
      <h1 className="mt-3 text-[27px] font-bold tracking-tighter text-[#2b3d30] sm:text-[34px]">{me.parent?.nickname}께 무슨 말을 전할까요?</h1>
      <p className="mt-3 text-sm leading-7 text-[#7c8775]">한 줄만 쓰면 AI가 15~20초 영상 대본으로 다듬어 드려요.</p>

      <div className="mt-8 grid items-start gap-6 lg:grid-cols-[1.5fr_1fr]">
      <section className="min-w-0 rounded-[28px] border border-[#e3e8df] bg-white p-6 shadow-[0_12px_40px_rgba(36,62,44,0.04)] sm:p-8">
      <div className="mb-6 flex items-center justify-between border-b border-[#edf0e8] pb-5"><h2 className="text-base font-bold text-[#3e5541]">오늘의 마음 한 줄</h2><span className="text-xs text-[#9aa48e]">To. {me.parent?.nickname}</span></div>
      <p className="mb-3 text-[11px] text-[#8a9681]">어떤 이야기를 전하고 싶으세요?</p>
      <div className="flex flex-wrap gap-2">
        {TEMPLATES.map((t) => (
          <button
            key={t.key}
            onClick={() => setTemplate(t.key)}
            className={`rounded-full border px-4 py-2 text-[15px] font-semibold ${
              template === t.key ? "border-[#315d4b] bg-[#315d4b] text-white" : "border-[#e5eadf] bg-[#fafbf7] text-[#809074] hover:border-[#bdcdb4]"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      <textarea
        value={memo}
        onChange={(e) => setMemo(e.target.value)}
        rows={6}
        maxLength={200}
        autoFocus
        placeholder={`예: ${current.example}`}
        className="mt-6 w-full resize-y rounded-2xl border border-[#e8ecdf] bg-[#fbfcf8] px-5 py-5 text-base leading-9 text-[#3e5541] outline-none placeholder:text-[#a3ad96] focus:border-[#9bb38b] focus:ring-4 focus:ring-[#f0f4e8]"
      />
      <p className="mb-5 mt-3 text-right text-[11px] text-[#9aa48e]">{memo.length} / 200</p>

      {error && <Notice tone="error">{error}</Notice>}
      <Button onClick={submit} disabled={!memo.trim()} loading={busy} className="mt-4 w-full py-4 text-lg">
        <Sparkles className="h-5 w-5" /> {busy ? "대본을 쓰고 있어요…" : "대본 만들기"}
      </Button>
      </section>
      <LetterCompanion recipient={me.parent?.nickname ?? "부모님"} example={current.example} />
      </div>
    </AppShell>
  );
}
