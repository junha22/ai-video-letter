"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Check, ShieldCheck } from "lucide-react";
import { api, errorText } from "@/lib/api";
import type { ConsentState } from "@/lib/types";
import { AppShell } from "@/components/AppShell";
import { Button, Notice, Spinner, StepHeader } from "@/components/ui";

type Kind = ConsentState["items"][number]["kind"];

export default function ConsentPage() {
  const router = useRouter();
  const [state, setState] = useState<ConsentState | null>(null);
  const [checked, setChecked] = useState<Record<Kind, boolean>>({ voice: false, face: false, parent_receive: false });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<ConsentState>("/api/consent")
      .then((s) => {
        if (s.ok) router.replace("/onboarding/parent");
        else setState(s);
      })
      .catch(() => router.replace("/"));
  }, [router]);

  const all = Object.values(checked).every(Boolean);

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      await api("/api/consent", { json: checked });
      router.push("/onboarding/parent");
    } catch (e) {
      setError(errorText(e));
      setBusy(false);
    }
  };

  return (
    <AppShell>
      <StepHeader
        step={1}
        total={4}
        title="시작하기 전에 동의가 필요해요"
        desc="온기는 내 목소리와 얼굴로 영상을 만들어요. 아래 내용을 확인해 주세요."
      />
      {!state ? (
        <Spinner />
      ) : (
        <>
          <button
            onClick={() => {
              const next = !all;
              setChecked({ voice: next, face: next, parent_receive: next });
            }}
            className="mb-3 flex w-full items-center gap-3 rounded-2xl border-2 border-ongi-700 bg-white px-4 py-4 text-left text-[17px] font-bold"
          >
            <Box on={all} />
            모두 동의해요
          </button>

          <div className="space-y-2">
            {state.items.map((item) => (
              <button
                key={item.kind}
                onClick={() => setChecked({ ...checked, [item.kind]: !checked[item.kind] })}
                className="flex w-full items-start gap-3 rounded-2xl border border-stone-200 bg-white px-4 py-4 text-left"
              >
                <Box on={checked[item.kind]} />
                <span>
                  <span className="block text-base font-bold text-stone-900">[필수] {item.title}</span>
                  <span className="mt-1 block text-sm leading-relaxed text-stone-600">{item.description}</span>
                </span>
              </button>
            ))}
          </div>

          <div className="mt-5 rounded-2xl bg-stone-100 p-4 text-sm leading-relaxed text-stone-700">
            <p className="mb-1 flex items-center gap-1.5 font-bold text-stone-900">
              <ShieldCheck className="h-4 w-4" /> 이렇게 지켜요
            </p>
            <ul className="list-disc space-y-1 pl-5">
              <li>영상은 내가 미리 보고 승인한 것만 보내져요.</li>
              <li>모든 영상에 &lsquo;AI로 만든 영상&rsquo; 표시가 들어가요.</li>
              <li>돈·계좌·인증번호를 요구하는 내용은 영상으로 만들 수 없어요.</li>
              <li>설정에서 동의를 철회하면 녹음, 목소리 모델, 사진, 영상이 모두 지워져요.</li>
            </ul>
          </div>

          {error && (
            <div className="mt-4">
              <Notice tone="error">{error}</Notice>
            </div>
          )}
          <Button onClick={submit} disabled={!all} loading={busy} className="mt-6 w-full">
            동의하고 계속하기
          </Button>
        </>
      )}
    </AppShell>
  );
}

function Box({ on }: { on: boolean }) {
  return (
    <span
      className={`mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-lg border-2 ${
        on ? "border-ongi-700 bg-ongi-700 text-white" : "border-stone-300 bg-white"
      }`}
    >
      {on && <Check className="h-4 w-4" strokeWidth={3} />}
    </span>
  );
}
