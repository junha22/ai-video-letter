"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Sparkles } from "lucide-react";
import { api, errorText } from "@/lib/api";
import type { Message } from "@/lib/types";
import { useMe } from "@/lib/useMe";
import { AppShell } from "@/components/AppShell";
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
      <h1 className="text-2xl font-extrabold text-stone-900">{me.parent?.nickname}께 무슨 말을 전할까요?</h1>
      <p className="mt-1 text-stone-600">한 줄만 쓰면 AI가 15~20초 영상 대본으로 다듬어 드려요.</p>

      <div className="mt-6 flex flex-wrap gap-2">
        {TEMPLATES.map((t) => (
          <button
            key={t.key}
            onClick={() => setTemplate(t.key)}
            className={`rounded-full border px-4 py-2 text-[15px] font-semibold ${
              template === t.key ? "border-ongi-700 bg-ongi-700 text-white" : "border-stone-300 bg-white text-stone-700"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      <textarea
        value={memo}
        onChange={(e) => setMemo(e.target.value)}
        rows={3}
        maxLength={200}
        autoFocus
        placeholder={`예: ${current.example}`}
        className="mt-4 w-full rounded-2xl border-2 border-stone-300 bg-white px-4 py-4 text-lg leading-relaxed outline-none focus:border-ongi-600"
      />
      <p className="mt-1 text-right text-sm text-stone-400">{memo.length} / 200</p>

      {error && <Notice tone="error">{error}</Notice>}
      <Button onClick={submit} disabled={!memo.trim()} loading={busy} className="mt-4 w-full py-4 text-lg">
        <Sparkles className="h-5 w-5" /> {busy ? "대본을 쓰고 있어요…" : "대본 만들기"}
      </Button>
    </AppShell>
  );
}
