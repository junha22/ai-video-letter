"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api, errorText } from "@/lib/api";
import type { Parent } from "@/lib/types";
import { AppShell } from "@/components/AppShell";
import { Button, Notice, Spinner, StepHeader } from "@/components/ui";

const PRESETS = [
  { nickname: "엄마", relation: "어머니" },
  { nickname: "아빠", relation: "아버지" },
  { nickname: "어머니", relation: "어머니" },
  { nickname: "아버지", relation: "아버지" },
  { nickname: "할머니", relation: "할머니" },
  { nickname: "할아버지", relation: "할아버지" },
];
const RELATIONS = ["어머니", "아버지", "할머니", "할아버지", "기타"];

const input =
  "w-full rounded-2xl border border-[#e3e8da] bg-[#fafbf7] px-4 py-3.5 text-base text-[#3e5541] outline-none placeholder:text-[#a1ab95] focus:border-[#9bb38b] focus:ring-4 focus:ring-[#f0f4e8]";

export default function ParentPage() {
  const router = useRouter();
  const [form, setForm] = useState<Parent>({ nickname: "", relation: "어머니", phone: "", tone_examples: "" });
  const [loaded, setLoaded] = useState(false);
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<Parent | null>("/api/parent")
      .then((p) => {
        if (p) {
          setForm(p);
          setEditing(true);
        }
        setLoaded(true);
      })
      .catch(() => router.replace("/"));
  }, [router]);

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      await api("/api/parent", { method: "PUT", json: form });
      router.push(editing ? "/home" : "/onboarding/voice");
    } catch (e) {
      setError(errorText(e));
      setBusy(false);
    }
  };

  return (
    <AppShell back={editing ? "/home" : undefined}>
      <StepHeader step={2} total={4} title="영상을 받으실 분을 알려 주세요" desc="대본에 들어갈 호칭과 말투를 맞추는 데 써요." />
      {!loaded ? (
        <Spinner />
      ) : (
        <div className="grid gap-x-8 gap-y-7 rounded-[28px] border border-[#e3e8df] bg-white p-6 shadow-[0_12px_40px_rgba(36,62,44,0.04)] sm:p-8 lg:grid-cols-2">
          <div className="border-b border-[#edf0e8] pb-5 lg:col-span-2"><p className="text-[10px] font-bold tracking-[0.16em] text-[#a77c65]">SOMEONE SPECIAL</p><h2 className="mt-2 text-xl font-bold text-[#3e5541]">가장 다정한 이름으로 불러 주세요</h2><p className="mt-2 text-xs leading-6 text-[#8a9681]">익숙한 호칭과 말투가 편지에 자연스럽게 담겨요.</p></div>
          <div>
            <label className="mb-2 block font-bold text-stone-800">평소에 뭐라고 부르세요?</label>
            <div className="mb-2 flex flex-wrap gap-2">
              {PRESETS.map((p) => (
                <button
                  key={p.nickname}
                  onClick={() => setForm({ ...form, ...p })}
                  className={`rounded-full border px-4 py-2 text-[15px] font-semibold ${
                    form.nickname === p.nickname
                      ? "border-[#315d4b] bg-[#315d4b] text-white"
                      : "border-[#e5eadf] bg-[#fafbf7] text-[#809074] hover:border-[#bdcdb4]"
                  }`}
                >
                  {p.nickname}
                </button>
              ))}
            </div>
            <input
              value={form.nickname}
              onChange={(e) => setForm({ ...form, nickname: e.target.value })}
              placeholder="직접 입력 (예: 어머님)"
              maxLength={20}
              className={input}
            />
          </div>

          <div>
            <label className="mb-2 block font-bold text-stone-800">관계</label>
            <select value={form.relation} onChange={(e) => setForm({ ...form, relation: e.target.value })} className={input}>
              {RELATIONS.map((r) => (
                <option key={r}>{r}</option>
              ))}
            </select>
          </div>

          <div>
            <label className="mb-2 block font-bold text-stone-800">휴대폰 번호</label>
            <input
              value={form.phone}
              onChange={(e) => setForm({ ...form, phone: e.target.value })}
              placeholder="010-1234-5678"
              inputMode="tel"
              className={input}
            />
          </div>

          <div>
            <label className="mb-1 block font-bold text-stone-800">
              평소 말투 <span className="font-normal text-stone-500">(선택)</span>
            </label>
            <p className="mb-2 text-sm text-stone-500">
              부모님께 자주 보내는 메시지를 2~3개 적어 주시면 대본을 내 말투처럼 써 드려요.
            </p>
            <textarea
              value={form.tone_examples}
              onChange={(e) => setForm({ ...form, tone_examples: e.target.value })}
              rows={3}
              maxLength={500}
              placeholder={"엄마 밥은 먹었어?\n오늘 좀 늦을 것 같아~ 먼저 자"}
              className={input}
            />
          </div>

          {error && <div className="lg:col-span-2"><Notice tone="error">{error}</Notice></div>}
          <Button onClick={submit} disabled={!form.nickname.trim() || !form.phone.trim()} loading={busy} className="w-full lg:col-span-2 lg:w-auto lg:min-w-48 lg:justify-self-end">
            {editing ? "저장" : "다음"}
          </Button>
        </div>
      )}
    </AppShell>
  );
}
