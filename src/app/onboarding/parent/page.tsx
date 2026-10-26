"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api, errorText } from "@/lib/api";
import type { Me, Parent } from "@/lib/types";
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
const LEVELS = [
  { value: "반말", example: (n: string) => `${n} 밥 먹었어? 오늘 좀 늦어~` },
  { value: "존댓말", example: (n: string) => `${n} 식사하셨어요? 오늘 좀 늦어요` },
] as const;

// 할머니·할아버지께는 대부분 존댓말이라 미리 골라 둔다. 엄마·아빠는 사람마다 달라서 비워 두고 메모 말투를 따른다
function defaultLevel(relation: string): Parent["speech_level"] {
  return relation === "할머니" || relation === "할아버지" ? "존댓말" : "";
}

const input =
  "w-full rounded-xl border border-stone-300 bg-white px-4 py-3 text-base outline-none focus:border-ongi-600";

export default function ParentPage() {
  const router = useRouter();
  const [form, setForm] = useState<Parent>({
    nickname: "",
    relation: "어머니",
    phone: "",
    child_call_name: "",
    speech_level: "",
    tone_examples: "",
  });
  // 사용자가 말투를 직접 고른 뒤에는 관계를 바꿔도 덮어쓰지 않는다
  const [levelTouched, setLevelTouched] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([api<Parent | null>("/api/parent"), api<Me>("/api/me")])
      .then(([p, me]) => {
        if (p) {
          setForm({ ...p, child_call_name: p.child_call_name || me.user.name });
          setLevelTouched(!!p.speech_level);
          setEditing(true);
        } else {
          // 카카오 닉네임이 별명일 수 있어서 처음 한 번 확인받는다
          setForm((f) => ({ ...f, child_call_name: me.user.name }));
        }
        setLoaded(true);
      })
      .catch(() => router.replace("/"));
  }, [router]);

  const setRelation = (next: Partial<Parent> & { relation: string }) =>
    setForm({ ...form, ...next, speech_level: levelTouched ? form.speech_level : defaultLevel(next.relation) });

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
      <StepHeader
        step={2}
        total={4}
        title="영상을 받으실 분을 알려 주세요"
        desc="대본에 들어갈 호칭과 말투를 맞추는 데 써요."
      />
      {!loaded ? (
        <Spinner />
      ) : (
        <div className="space-y-6">
          <div>
            <label className="mb-2 block font-bold text-stone-800">평소에 뭐라고 부르세요?</label>
            <div className="mb-2 flex flex-wrap gap-2">
              {PRESETS.map((p) => (
                <button
                  key={p.nickname}
                  onClick={() => setRelation(p)}
                  className={`rounded-full border px-4 py-2 text-[15px] font-semibold ${
                    form.nickname === p.nickname
                      ? "border-ongi-700 bg-ongi-700 text-white"
                      : "border-stone-300 bg-white text-stone-700"
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
            <select value={form.relation} onChange={(e) => setRelation({ relation: e.target.value })} className={input}>
              {RELATIONS.map((r) => (
                <option key={r}>{r}</option>
              ))}
            </select>
          </div>

          <div>
            <label className="mb-1 block font-bold text-stone-800">
              {form.nickname || "부모님"}께 평소 어떻게 말하세요?
            </label>
            <p className="mb-2 text-sm text-stone-500">대본을 이 말투로 써요. 고르지 않으면 메모 말투를 보고 정해요.</p>
            <div className="grid grid-cols-2 gap-2">
              {LEVELS.map((l) => {
                const on = form.speech_level === l.value;
                return (
                  <button
                    key={l.value}
                    onClick={() => {
                      setLevelTouched(true);
                      setForm({ ...form, speech_level: on ? "" : l.value });
                    }}
                    className={`rounded-2xl border-2 p-3 text-left ${
                      on ? "border-ongi-700 bg-ongi-50" : "border-stone-200 bg-white"
                    }`}
                  >
                    <span className="block font-bold text-stone-900">{l.value}</span>
                    <span className="mt-1 block text-sm leading-relaxed text-stone-600">
                      &ldquo;{l.example(form.nickname || "엄마")}&rdquo;
                    </span>
                  </button>
                );
              })}
            </div>
          </div>

          <div>
            <label className="mb-1 block font-bold text-stone-800">부모님이 나를 부르는 이름</label>
            <p className="mb-2 text-sm text-stone-500">
              대본과 부모님께 가는 메시지에 써요. (예: &ldquo;준하가 영상 편지를 보냈어요&rdquo;)
            </p>
            <input
              value={form.child_call_name}
              onChange={(e) => setForm({ ...form, child_call_name: e.target.value })}
              placeholder="예: 준하, 막내"
              maxLength={20}
              className={input}
            />
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
              자주 보내는 메시지 <span className="font-normal text-stone-500">(선택)</span>
            </label>
            <p className="mb-2 text-sm text-stone-500">
              2~3개 적어 주시면 자주 쓰는 표현까지 따라 해서 내가 쓴 것처럼 써 드려요.
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

          {error && <Notice tone="error">{error}</Notice>}
          <Button
            onClick={submit}
            disabled={!form.nickname.trim() || !form.phone.trim() || !form.child_call_name.trim()}
            loading={busy}
            className="w-full"
          >
            {editing ? "저장" : "다음"}
          </Button>
        </div>
      )}
    </AppShell>
  );
}
