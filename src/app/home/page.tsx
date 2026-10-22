"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ChevronRight, CircleCheck, Eye, PenLine } from "lucide-react";
import { api } from "@/lib/api";
import { formatDate, formatSeconds, STATUS_LABEL, TUNING_LABEL } from "@/lib/format";
import type { Me, Message } from "@/lib/types";
import { useMe } from "@/lib/useMe";
import { AppShell } from "@/components/AppShell";
import { Card, LinkButton, Notice, Spinner } from "@/components/ui";

const STATUS_STYLE: Record<string, string> = {
  draft: "bg-stone-100 text-stone-700",
  generating: "bg-amber-100 text-amber-900",
  ready: "bg-sky-100 text-sky-900",
  failed: "bg-red-100 text-red-800",
  approved: "bg-violet-100 text-violet-900",
  sent: "bg-ongi-100 text-ongi-900",
  viewed: "bg-emerald-100 text-emerald-900",
};

export default function HomePage() {
  const router = useRouter();
  const { me, reload } = useMe();
  const [messages, setMessages] = useState<Message[] | null>(null);

  const loadMessages = useCallback(() => {
    api<Message[]>("/api/messages")
      .then(setMessages)
      .catch(() => setMessages([]));
  }, []);

  useEffect(() => {
    loadMessages();
  }, [loadMessages]);

  // 처음 가입했거나 동의를 철회한 상태면 동의 화면부터
  useEffect(() => {
    if (me && !me.consent_ok) router.replace("/onboarding/consent");
  }, [me, router]);

  // 만드는 중인 영상이 있으면 상태를 계속 확인한다
  const generating = messages?.some((m) => m.status === "generating");
  useEffect(() => {
    if (!generating && me?.voice.status !== "processing") return;
    const t = window.setInterval(() => {
      loadMessages();
      reload();
    }, 4000);
    return () => window.clearInterval(t);
  }, [generating, me?.voice.status, loadMessages, reload]);

  const onNotification = () => {
    loadMessages();
    reload();
  };

  if (!me) {
    return (
      <AppShell>
        <Spinner />
      </AppShell>
    );
  }

  return (
    <AppShell onNotification={onNotification}>
      <h1 className="text-2xl font-extrabold text-stone-900">{me.user.name}님, 안녕하세요</h1>
      {me.parent && (
        <p className="mt-1 text-stone-600">오늘 {me.parent.nickname}께 한 줄 남겨 볼까요?</p>
      )}

      <Checklist me={me} />

      <div className="mt-6">
        {me.can_write ? (
          <LinkButton href="/messages/new" className="w-full py-5 text-lg">
            <PenLine className="h-5 w-5" /> 영상 편지 쓰기
          </LinkButton>
        ) : null}
        {me.can_write && !me.can_render && (
          <p className="mt-2 text-center text-sm text-stone-500">
            대본은 지금 써 둘 수 있고, 목소리·사진 등록이 끝나면 영상으로 만들 수 있어요.
          </p>
        )}
      </div>

      <h2 className="mb-3 mt-8 text-lg font-bold text-stone-900">보낸 영상 편지</h2>
      {messages === null ? (
        <Spinner />
      ) : messages.length === 0 ? (
        <p className="rounded-2xl bg-white px-4 py-8 text-center text-stone-500">아직 만든 영상 편지가 없어요</p>
      ) : (
        <ul className="space-y-3">
          {messages.map((m) => (
            <li key={m.id}>
              <Link href={`/messages/${m.id}`} className="block rounded-2xl border border-stone-200 bg-white p-4 hover:bg-stone-50">
                <div className="mb-2 flex items-center justify-between gap-2">
                  <span className={`rounded-full px-2.5 py-1 text-xs font-bold ${STATUS_STYLE[m.status] ?? ""}`}>
                    {m.status === "viewed" && <Eye className="mr-1 inline h-3.5 w-3.5" />}
                    {STATUS_LABEL[m.status] ?? m.status}
                  </span>
                  <span className="text-xs text-stone-400">{formatDate(m.viewed_at ?? m.created_at)}</span>
                </div>
                <p className="line-clamp-2 text-[15px] leading-relaxed text-stone-800">{m.script || m.memo}</p>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </AppShell>
  );
}

function Checklist({ me }: { me: Me }) {
  const voiceLabel = {
    none: "아직 안 했어요",
    recording: `${formatSeconds(me.voice.total_seconds)} / ${formatSeconds(me.voice.target_seconds)} 녹음함`,
    processing: "등록하는 중이에요 (끝나면 알려 드려요)",
    ready: me.voice.tuning ? `등록 완료 · ${TUNING_LABEL[me.voice.tuning]}` : "등록 완료",
    failed: "다시 등록이 필요해요",
  }[me.voice.status];

  const steps = [
    { done: me.consent_ok, title: "동의하기", desc: me.consent_ok ? "완료" : "목소리·얼굴 사용 동의", href: "/onboarding/consent" },
    {
      done: !!me.parent,
      title: "부모님 정보",
      desc: me.parent ? `${me.parent.nickname} · ${me.parent.phone}` : "호칭과 연락처",
      href: "/onboarding/parent",
    },
    { done: me.voice.status === "ready", title: "목소리 등록", desc: voiceLabel, href: "/onboarding/voice" },
    { done: !!me.photo, title: "얼굴 사진", desc: me.photo ? "등록 완료" : "정면 사진 1장", href: "/onboarding/photo" },
  ];
  const allDone = steps.every((s) => s.done);
  if (allDone) return null;
  const nextIndex = steps.findIndex((s) => !s.done);

  return (
    <Card className="mt-5">
      <p className="mb-3 font-bold text-stone-900">처음 한 번만 준비하면 돼요</p>
      {me.voice.status === "failed" && <Notice tone="error">{me.voice.error}</Notice>}
      <ul className="divide-y divide-stone-100">
        {steps.map((s, i) => {
          const locked = i > 0 && !me.consent_ok;
          return (
            <li key={s.title}>
              <Link
                href={locked ? "/onboarding/consent" : s.href}
                className={`flex items-center gap-3 py-3 ${i === nextIndex ? "" : "opacity-80"}`}
              >
                {s.done ? (
                  <CircleCheck className="h-6 w-6 shrink-0 text-emerald-600" />
                ) : (
                  <span
                    className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-sm font-bold ${
                      i === nextIndex ? "bg-ongi-700 text-white" : "bg-stone-200 text-stone-600"
                    }`}
                  >
                    {i + 1}
                  </span>
                )}
                <span className="flex-1">
                  <span className="block font-bold text-stone-900">{s.title}</span>
                  <span className="block text-sm text-stone-500">{s.desc}</span>
                </span>
                {!s.done && <ChevronRight className="h-5 w-5 text-stone-400" />}
              </Link>
            </li>
          );
        })}
      </ul>
    </Card>
  );
}
