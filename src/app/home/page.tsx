"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowRight, ChevronRight, CircleCheck, PenLine, Mail, Mic, Image as ImageIcon } from "lucide-react";
import { api, errorText } from "@/lib/api";
import { formatDate, formatSeconds, TUNING_LABEL } from "@/lib/format";
import type { Recipient } from "@/lib/conversations";
import type { Me, Message } from "@/lib/types";
import { useMe } from "@/lib/useMe";
import { DashboardShell } from "@/components/DashboardShell";
import { Card, Notice, Spinner } from "@/components/ui";
import { FamilyPortrait } from "@/components/album/FamilyPortrait";
import { AlbumCover, AlbumClosing } from "@/components/album/AlbumCover";
import { AlbumMemoryCard } from "@/components/album/AlbumMemoryCard";
import { kstDate } from "@/lib/conversations";

export default function HomePage() {
  const router = useRouter();
  const [familyFilter, setFamilyFilter] = useState("all");
  const [monthFilter, setMonthFilter] = useState("all");
  const { me, reload } = useMe();
  const [messages, setMessages] = useState<Message[] | null>(null);
  const [recipients, setRecipients] = useState<Recipient[] | null>(null);
  const [inboxError, setInboxError] = useState<string | null>(null);

  const loadMessages = useCallback(() => {
    api<Message[]>("/api/messages")
      .then(setMessages)
      .catch(() => setMessages([]));
    api<Recipient[]>("/api/recipients").then((rows) => { setRecipients(rows); setInboxError(null); }).catch((e) => setInboxError(errorText(e)));
  }, []);

  useEffect(() => {
    loadMessages();
  }, [loadMessages]);

  // 처음 가입했거나 동의를 철회한 상태면 동의 화면부터
  useEffect(() => {
    if (me && !me.consent_ok) router.replace("/onboarding/consent");
  }, [me, router]);

  // 만드는 중인 영상이 있거나 목소리를 등록·다듬는 중이면 상태를 계속 확인한다
  const generating = messages?.some((m) => m.status === "generating");
  const busy = generating || me?.voice.status === "processing";
  const tuning = me?.voice.tuning === "queued" || me?.voice.tuning === "training";
  useEffect(() => {
    if (!busy && !tuning) return;
    const t = window.setInterval(() => {
      loadMessages();
      reload();
    }, busy ? 4000 : 10000);
    return () => window.clearInterval(t);
  }, [busy, tuning, loadMessages, reload]);

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
      <AlbumCover owner={me.user.name} action={<Link href={me.can_write?"/messages/new":"/onboarding/consent"} className="album-primary"><PenLine size={17}/>오늘의 편지 쓰기 <ArrowRight size={17}/></Link>} description={me.can_write&&!me.can_render?"대본은 지금 써 둘 수 있어요. 목소리·사진을 준비하면 영상으로 만들 수 있어요.":undefined}/>

      <Checklist me={me} />

      <section id="album-records" className="album-record-section" aria-labelledby="album-record-title">
        <div className="album-section-head"><div><span className="album-eyebrow">PAGE BY PAGE</span><h2 id="album-record-title">차곡차곡, 우리의 안부</h2></div><Link href="/letters" className="album-text-link">가족별 대화와 기록 <ArrowRight size={16}/></Link></div>
        <div className="album-filters"><div role="group" aria-label="가족별 편지 필터"><button aria-pressed={familyFilter==="all"} onClick={()=>setFamilyFilter("all")}>우리 가족 모두</button>{recipients?.map(r=><button key={r.id} aria-pressed={familyFilter===String(r.id)} onClick={()=>setFamilyFilter(String(r.id))}>{r.nickname}께</button>)}</div><label htmlFor="album-month">기록한 달 <select aria-label="기록한 달" id="album-month" value={monthFilter} onChange={e=>setMonthFilter(e.target.value)}><option value="all">모든 달</option>{Array.from(new Set((messages||[]).map(m=>kstDate(new Date(m.approved_at||m.created_at)).slice(0,7)))).sort().reverse().map(month=><option key={month} value={month}>{month.replace("-","년 ")}월</option>)}</select></label></div>
        {messages===null?<Spinner label="가족의 편지를 모으고 있어요"/>:(messages||[]).filter(m=>(familyFilter==="all"||String(m.recipient_id)===familyFilter)&&(monthFilter==="all"||kstDate(new Date(m.approved_at||m.created_at)).startsWith(monthFilter))).length===0?<div className="album-empty"><Mail size={31}/><h3>아직 펼치지 않은 한 페이지</h3><p>이 조건에 맞는 편지가 없어요. 오늘의 안부로 다음 이야기를 시작해 보세요.</p><Link href={me.can_write?"/messages/new":"/onboarding/consent"} className="album-primary">첫 편지 쓰기 <ArrowRight size={16}/></Link></div>:<div className="album-records">{(messages||[]).filter(m=>(familyFilter==="all"||String(m.recipient_id)===familyFilter)&&(monthFilter==="all"||kstDate(new Date(m.approved_at||m.created_at)).startsWith(monthFilter))).map(m=><AlbumMemoryCard key={m.id} entry={{id:String(m.id),title:m.memo.trim()||m.template_label||"가족에게 전하는 안부",recipient:m.recipient?.nickname||m.parent_nickname||"가족",date:formatDate(m.approved_at||m.created_at),summary:m.script||"전하고 싶은 이야기를 다듬고 있어요.",status:({draft:"작성 중",generating:"영상 만드는 중",ready:"영상 확인하기",failed:"다시 확인이 필요해요",approved:"승인 완료",sent:"마음을 전했어요",viewed:"가족이 확인했어요"})[m.status],state:m.status,poster:m.poster_url,href:`/messages/${m.id}`}}/>)}</div>}
      </section>

      <h2 className="mb-4 mt-9 text-lg font-bold">마음을 전할 준비</h2>
      <div className="album-preparation-links grid gap-3 sm:grid-cols-3">
        {[
          { title: "부모님 정보", desc: me.parent ? `${me.parent.nickname} · 등록 완료` : "호칭과 연락처를 등록해 주세요", href: "/onboarding/parent", Icon: Mail, color: "bg-[#fff0e7]" },
          {
            title: "나의 목소리",
            desc:
              me.voice.status !== "ready"
                ? "목소리 등록 상태 확인하기"
                : me.voice.tuning
                  ? `목소리가 준비되었어요 · ${TUNING_LABEL[me.voice.tuning]}`
                  : "목소리가 준비되었어요",
            href: "/onboarding/voice",
            Icon: Mic,
            color: "bg-[#fae8de]",
          },
          { title: "얼굴 사진", desc: me.photo ? "사진이 준비되었어요" : "밝은 정면 사진을 준비해 주세요", href: "/onboarding/photo", Icon: ImageIcon, color: "bg-[#f9eced]" },
        ].map(({ title, desc, href, Icon, color }) => (
          <Link key={href} href={me.consent_ok ? href : "/onboarding/consent"} className="rounded-[19px] border border-[#ead9cd] bg-white p-5 shadow-sm transition-colors hover:border-[#ead9cd]">
            <span className={`mb-4 flex h-11 w-11 items-center justify-center rounded-2xl text-[#c8493c] ${color}`}><Icon size={23} /></span>
            <span className="block text-sm font-bold">{title}</span>
            <span className="mt-1 block break-words text-xs leading-6 text-stone-500">{desc}</span>
          </Link>
        ))}
      </div>

      <div id="letters" className="mb-4 mt-9 flex scroll-mt-24 items-center justify-between gap-3">
        <h2 className="text-lg font-bold">대상자별 영상 편지함</h2>
        <Link href="/letters" className="inline-flex min-h-11 items-center gap-1 text-sm font-bold text-[#c8493c]">전체 보기·대상 추가 <ChevronRight size={16} /></Link>
      </div>
      <p className="mb-4 text-sm leading-7 text-stone-500">대상자를 누르면 오늘의 대화와 날짜별 지난 편지, 월간 답글 포트폴리오를 볼 수 있어요.</p>
      {inboxError && <Notice tone="error">{inboxError} <button onClick={loadMessages} className="ml-2 underline">다시 불러오기</button></Notice>}
      {recipients === null && !inboxError ? (
        <Spinner />
      ) : recipients?.length === 0 ? (
        <div className="rounded-[22px] border border-[#ead9cd] bg-white px-4 py-12 text-center"><Mail className="mx-auto mb-4 h-8 w-8 text-[#81645d]" /><p className="text-sm text-stone-500">편지를 주고받을 분을 등록해 주세요.</p><Link href="/letters" className="mt-4 inline-block font-bold text-[#c8493c] underline">대상자 등록하기</Link></div>
      ) : (
        <ul className="grid gap-4 sm:grid-cols-2">
          {recipients?.map((r) => (
            <li key={r.id}>
              <Link href={`/conversations/${r.id}`} className="album-recipient-link block h-full rounded-[22px] border border-[#ead9cd] bg-white p-5 shadow-sm transition-colors hover:border-[#ead9cd]">
                <div className="mb-4 flex items-center gap-3"><FamilyPortrait relation={r.relation} name={r.nickname} className="family-home-portrait"/><div className="min-w-0 flex-1"><h3 className="font-bold">{r.nickname}</h3><p className="text-xs text-stone-500">{r.relation} · 영상 {r.video_count}개 · 답글 {r.reply_count}개</p></div></div>
                <p className="line-clamp-2 min-h-12 text-sm leading-6 text-stone-600">{r.last_preview || "첫 영상 편지를 보내고 대화를 시작해 보세요."}</p>
                <div className="mt-4 flex items-center justify-between gap-2"><span className="text-xs text-stone-500">{r.last_activity_at ? formatDate(r.last_activity_at) : "아직 대화가 없어요"}</span><span className="inline-flex items-center gap-1 text-xs font-bold text-[#c8493c]">대화 보기 <ChevronRight size={14} /></span></div>
              </Link>
            </li>
          ))}
        </ul>
      )}
      <AlbumClosing action={<Link href={me.can_write?"/messages/new":"/onboarding/consent"} className="album-text-link">다음 페이지에 마음 남기기 <ArrowRight size={18}/></Link>}/>
    </DashboardShell>
  );
}

function Checklist({ me }: { me: Me }) {
  const voiceLabel = {
    none: "아직 안 했어요",
    recording: me.voice.basic_ready
      ? "한 문장 녹음 완료 · 등록 버튼을 눌러 주세요"
      : me.voice.total_seconds > 0
        ? `${formatSeconds(me.voice.total_seconds)} 녹음함 · 대본 한 문장이면 돼요`
        : "대본 한 문장이면 돼요",
    processing: "등록하는 중이에요 (끝나면 알려 드려요)",
    ready: me.voice.tuning ? `등록 완료 · ${TUNING_LABEL[me.voice.tuning]}` : "등록 완료 · 기본 목소리",
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
    <Card className="mt-6 !rounded-[22px] !border-[#ead9cd] !bg-[#fae8de] sm:p-6">
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
                      i === nextIndex ? "bg-[#c8493c] text-white" : "bg-stone-200 text-stone-600"
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
