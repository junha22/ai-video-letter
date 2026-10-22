"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ChevronRight, CircleCheck, Eye, PenLine, Mail, Mic, Image as ImageIcon } from "lucide-react";
import { api } from "@/lib/api";
import { formatDate, formatSeconds, STATUS_LABEL, TUNING_LABEL } from "@/lib/format";
import type { Me, Message } from "@/lib/types";
import { useMe } from "@/lib/useMe";
import { DashboardShell } from "@/components/DashboardShell";
import { Card, Notice, Spinner } from "@/components/ui";
import { FamilyIllustration } from "./FamilyIllustration";

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
      <DashboardShell>
        <Spinner />
      </DashboardShell>
    );
  }

  return (
    <DashboardShell onNotification={onNotification}>
      <p className="text-xs font-extrabold tracking-[0.16em] text-[#b77560]">WITH YOUR HEART</p>
      <h1 className="mt-2 text-[28px] font-extrabold tracking-tight sm:text-[32px]">안녕하세요, {me.user.name}님</h1>
      {me.parent && (
        <p className="mt-2 text-sm text-stone-500">오늘 {me.parent.nickname}께 한 줄 남겨 볼까요?</p>
      )}

      <section className="relative mt-6 grid overflow-hidden rounded-[25px] bg-[#f4eadb] shadow-[0_18px_48px_rgba(52,67,52,0.08)] md:grid-cols-[1fr_47%]">
        <div className="px-6 py-7 sm:px-10 sm:py-12">
          <p className="text-xs font-bold text-[#96715f]">마음이 닿는 가장 다정한 방법</p>
          <h2 className="mt-3 text-3xl font-extrabold leading-snug tracking-tighter sm:mt-4 sm:text-4xl">멀리 있어도,<br /><span className="text-[#42735d]">마음은 가까이.</span></h2>
          <p className="mb-5 mt-3 text-sm leading-7 text-[#81786a]">익숙한 얼굴과 목소리로 전하는 안부.<br />부모님의 오늘에 작은 기쁨을 선물하세요.</p>
        {me.can_write ? (
          <Link href="/messages/new" className="inline-flex min-h-12 w-full items-center justify-center gap-3 rounded-2xl bg-[#315d4b] px-5 py-3 text-sm font-bold text-white transition-colors hover:bg-[#234b39] sm:w-auto">
            <PenLine className="h-4 w-4" /> 영상 편지 쓰기 <ChevronRight size={16} />
          </Link>
        ) : null}
        {me.can_write && !me.can_render && (
          <p className="mt-3 max-w-sm text-sm leading-6 text-stone-600">
            대본은 지금 써 둘 수 있고, 목소리·사진 등록이 끝나면 영상으로 만들 수 있어요.
          </p>
        )}
        </div>
        <div className="hidden md:block"><FamilyIllustration /></div>
      </section>

      <Checklist me={me} />

      <h2 className="mb-4 mt-9 text-lg font-bold">마음을 전할 준비</h2>
      <div className="grid gap-3 sm:grid-cols-3">
        {[
          { title: "부모님 정보", desc: me.parent ? `${me.parent.nickname} · 등록 완료` : "호칭과 연락처를 등록해 주세요", href: "/onboarding/parent", Icon: Mail, color: "bg-[#fff0e7]" },
          { title: "나의 목소리", desc: me.voice.status === "ready" ? "목소리가 준비되었어요" : "목소리 등록 상태 확인하기", href: "/onboarding/voice", Icon: Mic, color: "bg-[#e9f0e8]" },
          { title: "얼굴 사진", desc: me.photo ? "사진이 준비되었어요" : "밝은 정면 사진을 준비해 주세요", href: "/onboarding/photo", Icon: ImageIcon, color: "bg-[#f9eced]" },
        ].map(({ title, desc, href, Icon, color }) => (
          <Link key={href} href={me.consent_ok ? href : "/onboarding/consent"} className="rounded-[19px] border border-[#e8e9e2] bg-white p-5 shadow-sm transition-colors hover:border-[#bccdc0]">
            <span className={`mb-4 flex h-11 w-11 items-center justify-center rounded-2xl text-[#315d4b] ${color}`}><Icon size={23} /></span>
            <span className="block text-sm font-bold">{title}</span>
            <span className="mt-1 block break-words text-xs leading-6 text-stone-500">{desc}</span>
          </Link>
        ))}
      </div>

      <div id="letters" className="mb-4 mt-9 flex scroll-mt-24 items-center justify-between gap-3">
        <h2 className="text-lg font-bold">나의 영상 편지</h2>
        {messages !== null && <span className="text-xs text-stone-500">전체 {messages.length}개</span>}
      </div>
      {messages === null ? (
        <Spinner />
      ) : messages.length === 0 ? (
        <div className="rounded-[22px] border border-[#e8e9e2] bg-white px-4 py-12 text-center"><Mail className="mx-auto mb-4 h-8 w-8 text-[#7f9b84]" /><p className="text-sm text-stone-500">아직 만든 영상 편지가 없어요</p></div>
      ) : (
        <ul className="grid gap-4 sm:grid-cols-2">
          {messages.map((m) => (
            <li key={m.id}>
              <Link href={`/messages/${m.id}`} className="block h-full rounded-[22px] border border-[#e8e9e2] bg-white p-5 shadow-sm transition-colors hover:border-[#bccdc0]">
                <div className="mb-2 flex items-center justify-between gap-2">
                  <span className={`rounded-full px-2.5 py-1 text-xs font-bold ${STATUS_STYLE[m.status] ?? ""}`}>
                    {m.status === "viewed" && <Eye className="mr-1 inline h-3.5 w-3.5" />}
                    {STATUS_LABEL[m.status] ?? m.status}
                  </span>
                  <span className="text-xs text-stone-500">{formatDate(m.viewed_at ?? m.created_at)}</span>
                </div>
                <p className="line-clamp-2 text-[15px] leading-relaxed text-stone-800">{m.script || m.memo}</p>
                <span className="mt-4 flex items-center justify-end gap-1 text-xs font-bold text-[#315d4b]">편지 보기 <ChevronRight size={14} /></span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </DashboardShell>
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
      desc: me.parent ? `${me.parent.nickname} · 등록 완료` : "호칭과 연락처",
      href: "/onboarding/parent",
    },
    { done: me.voice.status === "ready", title: "목소리 등록", desc: voiceLabel, href: "/onboarding/voice" },
    { done: !!me.photo, title: "얼굴 사진", desc: me.photo ? "등록 완료" : "정면 사진 1장", href: "/onboarding/photo" },
  ];
  const allDone = steps.every((s) => s.done);
  if (allDone) return null;
  const nextIndex = steps.findIndex((s) => !s.done);

  return (
    <Card className="mt-6 !rounded-[22px] !border-[#dce9db] !bg-[#e9f0e9] sm:p-6">
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
                      i === nextIndex ? "bg-[#315d4b] text-white" : "bg-stone-200 text-stone-600"
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
