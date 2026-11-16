"use client";

import { useCallback, useEffect, useRef, useState } from "react";
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
import { useAlbumCover } from "@/components/album/useAlbumCover";
import { AlbumCoverEditor } from "@/components/album/AlbumCoverEditor";
import { FamilyAlbumCard } from "@/components/album/FamilyAlbumCard";
import { RecipientPhotoEditor } from "@/components/album/RecipientPhotoEditor";
import { AlbumCover, AlbumClosing } from "@/components/album/AlbumCover";

export default function HomePage() {
  const router = useRouter();
  const { me, reload } = useMe();
  const cover = useAlbumCover({ enabled: !!me });
  const [messages, setMessages] = useState<Message[] | null>(null);
  const [recipients, setRecipients] = useState<Recipient[] | null>(null);
  const [inboxError, setInboxError] = useState<string | null>(null);
  const recipientVersion = useRef(0);

  const loadMessages = useCallback(() => {
    api<Message[]>("/api/messages")
      .then(setMessages)
      .catch(() => setMessages([]));
    const version = ++recipientVersion.current;
    api<Recipient[]>("/api/recipients").then((rows) => { if (version !== recipientVersion.current) return; setRecipients(rows); setInboxError(null); }).catch((e) => { if (version === recipientVersion.current) setInboxError(errorText(e)); });
  }, []);

  useEffect(() => {
    loadMessages();
    return () => { recipientVersion.current += 1; };
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
      <AlbumCover coverImage={cover.url} coverEditor={<AlbumCoverEditor cover={cover}/>} owner={me.user.name} action={<Link href={me.can_write?"/messages/new":"/onboarding/consent"} className="album-primary"><PenLine size={17}/>오늘의 편지 쓰기 <ArrowRight size={17}/></Link>} description={me.can_write&&!me.can_render?"대본은 지금 써 둘 수 있어요. 목소리·사진을 준비하면 영상으로 만들 수 있어요.":undefined}/>

      <Checklist me={me} />

      <section id="album-records" className="album-record-section" aria-labelledby="album-record-title">
        <div className="album-section-head"><div><span className="album-eyebrow">ONE ALBUM, ONE SPECIAL PERSON</span><h2 id="album-record-title">차곡차곡, 우리 이야기</h2><p className="family-album-intro">가족마다 한 권씩, 함께 쌓아 가는 마음의 앨범.</p></div><Link href="/letters" className="album-text-link">가족 추가·관리 <ArrowRight size={16}/></Link></div>
        {inboxError && <div role="alert"><Notice tone="error">{inboxError} <button type="button" onClick={loadMessages} className="ml-2 underline">다시 불러오기</button></Notice></div>}
        {recipients === null ? (!inboxError && <Spinner label="가족 앨범을 불러오고 있어요"/>) : recipients.length === 0 ? <div className="album-empty"><Mail size={31}/><h3>우리 가족의 첫 앨범을 펼쳐 볼까요?</h3><p>가족을 추가하면 그 사람과 주고받은 편지가 한 권의 앨범에 모여요.</p><Link href="/letters" className="album-primary">가족 앨범 만들기 <ArrowRight size={16}/></Link></div> : <div className={`family-album-grid ${recipients.length > 2 ? "family-album-grid-many" : ""}`}>{recipients.map(r=><FamilyAlbumCard key={r.id} album={{id:r.id,name:r.nickname,relation:r.relation,photoUrl:r.photo?.url,letterCount:r.video_count,replyCount:r.reply_count,latest:r.last_activity_at?formatDate(r.last_activity_at):null,href:`/conversations/${r.id}`}} editor={<RecipientPhotoEditor variant="album-cover" recipientId={r.id} name={r.nickname} photoUrl={r.photo?.url} onChange={photo=>{recipientVersion.current+=1;setInboxError(null);setRecipients(rows=>rows?.map(person=>person.id===r.id?{...person,photo}:person)??null);}}/>}/>)}</div>}
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
