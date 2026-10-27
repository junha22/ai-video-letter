"use client";

import { useState, type ComponentProps, type ReactNode } from "react";
import { ArrowLeft, ArrowRight, Camera, Check, Heart, House, Leaf, Mic, MonitorPlay, PenLine, Play, ShieldCheck, Sparkles } from "lucide-react";
import { Button, Card } from "@/components/ui";
import { FamilyIllustration } from "../home/FamilyIllustration";
import { LoginPreview } from "./LoginPreview";
import { LetterCompanion, PhotoGuide, VoiceWorkspace } from "@/components/StudioPanels";
import { SamplePortrait } from "@/components/SamplePortrait";
import voiceSentences from "../../../shared/voice-sentences.json";

// 이 모듈은 프리뷰 전용이다. 실제 화면, 인증 훅, 알림, API 모듈을 불러오지 않는다.
const SCREENS = [
  { id: "main", label: "메인 화면", Icon: Heart },
  { id: "login", label: "로그인 화면", Icon: ShieldCheck },
  { id: "dashboard", label: "대시보드", Icon: House },
  { id: "register", label: "음성·사진 등록", Icon: Mic },
  { id: "compose", label: "메시지 작성", Icon: PenLine },
  { id: "review", label: "영상 미리보기", Icon: MonitorPlay },
  { id: "watch", label: "부모님 시청", Icon: Play },
] as const;
type Screen = (typeof SCREENS)[number]["id"];

const TOPICS = {
  안부: "엄마, 오늘 하루는 어땠어요? 밥 잘 챙겨 드시고, 오늘도 편안한 하루 보내요. 사랑해요!",
  건강: "엄마, 아침저녁으로 쌀쌀해졌어요. 따뜻하게 입고 식사도 꼭 챙겨 드세요. 곧 찾아뵐게요!",
  생일: "엄마, 생신 정말 축하드려요! 늘 건강하고 행복하세요. 오늘은 누구보다 좋은 하루 보내요!",
};
const LETTERS = [
  { title: "엄마께 보내는 아침 안부", date: "10월 20일", status: "시청 완료", icon: "💌" },
  { title: "건강 챙겨요, 엄마", date: "10월 18일", status: "작성 중", icon: "☕" },
];

function PreviewButton({ secondary = false, className = "", ...props }: ComponentProps<typeof Button> & { secondary?: boolean }) {
  return <Button {...props} type="button" variant={secondary ? "secondary" : "primary"} className={`!rounded-[13px] !px-5 !py-3 !text-sm ${secondary ? "!border-[#e6e7e1] !text-[#596a5f]" : "!bg-[#315d4b] !text-white hover:!bg-[#234b39]"} ${className}`} />;
}

function PreviewCard({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <Card className={`!rounded-[22px] !border-[#e8e9e2] sm:p-7 ${className}`}>{children}</Card>;
}

export function DevPreview() {
  const [screen, setScreen] = useState<Screen>("main");
  const [sampleCharacter, setSampleCharacter] = useState<"son" | "daughter">("son");
  const [topic, setTopic] = useState<keyof typeof TOPICS>("안부");
  const [message, setMessage] = useState<string>(TOPICS.안부);
  const [voiceReady, setVoiceReady] = useState(false);
  const [sentenceIndex, setSentenceIndex] = useState(0);
  const [photoReady, setPhotoReady] = useState(false);
  const [reviewReady, setReviewReady] = useState(false);
  const [watching, setWatching] = useState(false);
  const [reaction, setReaction] = useState("");
  const [notice, setNotice] = useState("");
  const current = SCREENS.find((item) => item.id === screen)!;

  function navigate(next: Screen) {
    setScreen(next);
    setNotice("");
  }

  const navigation = SCREENS.map(({ id, label, Icon }) => (
    <button key={id} type="button" onClick={() => navigate(id)} aria-current={screen === id ? "page" : undefined}
      className={`flex min-h-11 shrink-0 items-center gap-3 rounded-[13px] px-4 py-3 text-left text-sm font-semibold transition-colors ${screen === id ? "bg-[#e7efe7] text-[#315d4b]" : "text-[#68736b] hover:bg-[#f1f4ee]"}`}>
      <Icon size={19} aria-hidden="true" /><span>{label}</span>
    </button>
  ));

  const heading = (eyebrow: string, title: string, description: string) => (
    <div className="mb-7">
      <p className="text-[11px] font-extrabold tracking-[0.16em] text-[#b77560]">{eyebrow}</p>
      <h1 className="mb-2 mt-2 text-[27px] font-extrabold leading-tight tracking-tighter sm:text-[32px]">{title}</h1>
      <p className="text-sm leading-7 text-[#737d74]">{description}</p>
    </div>
  );

  const hero = (
    <section className="grid overflow-hidden rounded-[25px] bg-[#f4eadb] shadow-[0_18px_48px_rgba(52,67,52,0.08)] md:grid-cols-[1fr_47%]">
      <div className="px-6 py-7 sm:px-11 sm:py-12">
        <p className="text-xs font-bold text-[#96715f]">💌 마음이 닿는 가장 다정한 방법</p>
        <h2 className="mt-4 text-[34px] font-extrabold leading-snug tracking-tighter lg:text-[39px]">멀리 있어도,<br /><span className="text-[#42735d]">마음은 가까이.</span></h2>
        <p className="mb-6 mt-4 text-sm leading-7 text-[#81786a]">익숙한 얼굴과 목소리로 전하는 안부.<br />부모님의 오늘에 작은 기쁨을 선물하세요.</p>
        <PreviewButton className="w-full sm:w-auto" onClick={() => navigate(screen === "main" ? "dashboard" : "compose")}>{screen === "main" ? "샘플 대시보드 둘러보기" : "영상 편지 만들기"}<ArrowRight size={16} /></PreviewButton>
      </div>
      <FamilyIllustration />
    </section>
  );

  return (
    <div className="min-h-screen bg-[#f8f7f2] text-[#2e342f] tracking-[-0.035em] [&_button:focus-visible]:outline [&_button:focus-visible]:outline-2 [&_button:focus-visible]:outline-offset-4 [&_button:focus-visible]:outline-[#b77560]">
      <a href="#preview-content" className="sr-only z-50 focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:rounded-xl focus:bg-white focus:p-3">프리뷰 본문으로 이동</a>
      <aside className="fixed inset-y-0 left-0 hidden w-[252px] flex-col border-r border-[#eae9e3] bg-[#fdfcf8] px-5 py-9 lg:flex">
        <button type="button" onClick={() => navigate("main")} className="flex items-center gap-3 px-2 text-left text-[28px] font-black text-[#315d4b]">
          <span className="flex h-9 w-9 -rotate-6 items-center justify-center rounded-xl bg-[#315d4b] text-white"><Heart size={20} /></span>
          <span>온기<small className="block text-[11px] font-normal tracking-normal text-[#828983]">마음을 잇는 영상 편지</small></span>
        </button>
        <p className="mb-3 mt-10 px-4 text-[11px] font-bold tracking-widest text-[#828983]">DESIGN PREVIEW</p>
        <nav aria-label="개발 프리뷰 화면" className="grid gap-2">{navigation}</nav>
        <div className="mt-auto pt-8">
          <div className="rounded-2xl border border-[#e0e8db] bg-[#f0f5ed] p-4"><Leaf className="mb-2 text-[#60896c]" size={24} /><strong className="text-sm">마음을 전하는 작은 시작</strong><p className="mt-2 text-xs leading-6 text-[#737d74]">이 공간의 인물과 편지는 모두 샘플입니다.</p></div>
          <p className="px-2 pt-5 text-sm font-bold">😊 지민님 <span className="ml-1 text-xs font-normal text-[#737d74]">샘플 프로필</span></p>
        </div>
      </aside>
      <div className="lg:pl-[252px]">
        <div className="border-b border-[#ead4b2] bg-[#fff2db] px-5 py-3 text-center text-xs font-semibold leading-6 text-[#77542c]">
          개발 전용 프리뷰 · 샘플 데이터 · 실제 서비스와 별개입니다. 입력은 저장되지 않으며 녹음·AI 생성·발송을 수행하지 않습니다.
        </div>
        <header className="mx-auto flex max-w-[1348px] flex-wrap items-center justify-between gap-3 px-5 py-5 sm:px-10">
          <span className="text-sm text-[#737d74]"><strong className="mr-3 text-xl text-[#315d4b] lg:hidden">온기</strong>PREVIEW / {current.label}</span>
          <div className="flex flex-wrap items-center gap-3">
            <div role="group" aria-label="미리보기 캐릭터 선택" className="flex items-center gap-1 rounded-full border border-[#e0e8db] bg-white p-1">
              {([{ id: "son", label: "아들 예시" }, { id: "daughter", label: "딸 예시" }] as const).map(({ id, label }) => <button key={id} type="button" aria-pressed={sampleCharacter === id} onClick={() => setSampleCharacter(id)} className={`min-h-9 rounded-full px-3 text-xs font-semibold transition-colors ${sampleCharacter === id ? "bg-[#315d4b] text-white" : "text-[#68736b] hover:bg-[#f1f4ee]"}`}>{label}</button>)}
            </div>
            <span className="rounded-full border border-[#e0e8db] bg-[#eff3ec] px-3 py-1.5 text-[11px] font-bold text-[#52705c]">샘플 데이터 · DEVELOPMENT ONLY</span>
          </div>
        </header>
        <nav aria-label="모바일 개발 프리뷰 화면" className="sticky top-0 z-30 flex gap-2 overflow-x-auto border-y border-[#e8e9e2] bg-[#fdfcf8]/95 px-5 py-3 backdrop-blur lg:hidden">{navigation}</nav>
        <main id="preview-content" className="mx-auto max-w-[1348px] px-5 pb-14 pt-5 sm:px-10 sm:pt-7">
          {screen === "login" && <LoginPreview />}
          {screen === "main" && <>
            {heading("A LITTLE CLOSER", "마음이 전해지는 순간, 온기", "‘곁에’ 디자인 시안을 바탕으로 한 개발 프리뷰입니다. 서비스 브랜드는 온기를 유지합니다.")}
            {hero}
            <div className="mt-7 grid gap-4 sm:grid-cols-3">
              {[
                { title: "나의 목소리로", desc: "익숙한 목소리에 마음을 담아요", Icon: Mic, to: "register" },
                { title: "한 줄의 마음을", desc: "짧은 안부도 따뜻한 편지가 돼요", Icon: PenLine, to: "compose" },
                { title: "가족에게 가까이", desc: "크고 편안한 화면으로 만나요", Icon: Heart, to: "watch" },
              ].map(({ title, desc, Icon, to }) => <PreviewCard key={title}><Icon className="mb-4 text-[#60896c]" /><h2 className="font-bold">{title}</h2><p className="mb-4 mt-2 text-xs leading-6 text-[#737d74]">{desc}</p><button type="button" onClick={() => navigate(to as Screen)} className="text-xs font-bold text-[#315d4b]">화면 둘러보기 →</button></PreviewCard>)}
            </div>
          </>}

          {screen === "dashboard" && <>
            {heading("GOOD AFTERNOON", "안녕하세요, 지민님 👋", "오늘도 소중한 가족에게 따뜻한 마음을 전해 보세요. · 샘플 프로필")}
            {hero}
            <h2 className="mb-4 mt-9 text-xl font-bold">어떤 마음을 전할까요?</h2>
            <div className="grid gap-4 sm:grid-cols-3">{([
              ["안부", "💌", "오늘의 안부", "별일 없어도 전하는 따뜻한 한마디"],
              ["건강", "🍀", "건강 챙기기", "식사와 날씨, 다정하게 챙겨요"],
              ["생일", "🎂", "특별한 날", "생일과 기념일을 영상 편지로"],
            ] as const).map(([key, emoji, title, desc]) => <button type="button" key={key} onClick={() => { setTopic(key); setMessage(TOPICS[key]); navigate("compose"); }} className="rounded-[19px] border border-[#e8e9e2] bg-white p-5 text-left shadow-sm transition-colors hover:border-[#bccdc0]"><span className="mb-4 flex h-11 w-11 items-center justify-center rounded-xl bg-[#fff0e7] text-2xl">{emoji}</span><strong className="block text-sm">{title}</strong><small className="mt-1 block leading-6 text-[#737d74]">{desc}</small></button>)}</div>
            <h2 className="mb-4 mt-9 text-xl font-bold">최근 편지 <span className="text-xs font-normal text-[#737d74]">샘플 2개</span></h2>
            <div className="grid gap-4 md:grid-cols-[1.4fr_1fr]">
              <PreviewCard>{LETTERS.map((letter) => <button key={letter.title} type="button" onClick={() => navigate("review")} className="flex w-full flex-wrap items-center gap-3 border-b border-[#f0f0eb] py-4 text-left last:border-0"><span className="flex h-12 w-12 items-center justify-center rounded-xl bg-[#f6efe3] text-2xl">{letter.icon}</span><span className="flex-1"><strong className="block text-sm">{letter.title}</strong><small className="text-[#737d74]">{letter.date} · 샘플 편지</small></span><span className="rounded-full bg-[#eaf3e9] px-3 py-1 text-xs text-[#52705c]">{letter.status}</span></button>)}</PreviewCard>
              <section className="rounded-[22px] border border-[#dce9db] bg-[#e7efe6] p-7"><Leaf className="mb-3 text-[#60896c]" /><h3 className="text-xl font-bold">목소리로 전하는<br />작은 위로</h3><p className="mb-5 mt-3 text-sm leading-7 text-[#647b67]">나의 목소리와 얼굴로 소중한 사람을 위한 영상 편지를 준비해요.</p><PreviewButton secondary onClick={() => navigate("register")}>등록 화면 보기 <ArrowRight size={16} /></PreviewButton></section>
            </div>
          </>}

          {screen === "register" && <>
            {heading("VOICE & FACE", "목소리와 사진을 준비해 주세요", "음성 사전 녹음은 총 2분 15초를 목표로 합니다. 이 화면은 샘플이며 마이크·카메라·파일에 접근하지 않습니다.")}
            <VoiceWorkspace
              reading={<><p className="mb-5 text-xs font-semibold text-[#73906d]">읽기 연습 · 샘플 대본 {sentenceIndex + 1} / {voiceSentences.length} · 약 10초</p><blockquote className="text-[25px] font-semibold leading-[1.8] tracking-tight text-[#344a38] sm:text-[30px]">“{voiceSentences[sentenceIndex].text}”</blockquote><div className="mt-5 flex justify-between gap-3"><button type="button" disabled={sentenceIndex === 0} onClick={() => setSentenceIndex(sentenceIndex - 1)} className="min-h-11 text-xs font-semibold text-[#52705c] disabled:opacity-30">이전 대본</button><button type="button" disabled={sentenceIndex === voiceSentences.length - 1} onClick={() => setSentenceIndex(sentenceIndex + 1)} className="min-h-11 text-xs font-semibold text-[#52705c] disabled:opacity-30">다음 대본</button></div><div role="progressbar" aria-label="샘플 녹음 진행률" aria-valuemin={0} aria-valuemax={100} aria-valuenow={voiceReady ? 100 : 0} className="mt-7 h-1.5 overflow-hidden rounded-full bg-[#e7ebe4]"><div className={`h-full rounded-full bg-[#315d4b] ${voiceReady ? "w-full" : "w-0"}`} /></div><p className="mt-3 text-[11px] text-[#98a18e]">샘플 상태: {voiceReady ? "등록 완료 · 100%" : "등록 전 · 0%"}</p></>}
              controls={<><span className="mb-6 flex h-24 w-24 items-center justify-center rounded-full bg-[#f0ecd9] text-[#284f3e] shadow-[0_0_0_10px_rgba(255,255,255,0.05)]"><Mic size={34} strokeWidth={1.5} /></span><strong className="mb-5 text-sm font-medium text-[#e5ecdc]">{voiceReady ? "샘플 등록 완료" : "목소리 등록 프리뷰"}</strong><button type="button" onClick={() => setVoiceReady(!voiceReady)} className="min-h-12 w-full rounded-2xl border border-white/25 px-5 py-3 text-sm font-medium text-[#e9eddb] transition-colors hover:bg-white/10">{voiceReady ? "등록 전 상태 보기" : "완료 상태 보기"}</button><p className="mt-4 text-[11px] text-[#9bb398]">실제 녹음·학습 없음</p></>}
            />
            <div className="mb-5 mt-9"><p className="text-[10px] font-bold tracking-[0.16em] text-[#a77c65]">ONE FAMILIAR FACE</p><h3 className="mt-2 text-xl font-bold">마음에 담을 나의 얼굴</h3></div>
            <div className="grid items-start gap-6 lg:grid-cols-[0.85fr_1.15fr]">
              <PhotoGuide variant={sampleCharacter === "son" ? "daughter" : "son"} />
              <div className="rounded-[28px] border border-[#e3e8df] bg-white p-6 sm:p-8">
              <button type="button" onClick={() => setPhotoReady(!photoReady)} className="flex min-h-[320px] w-full flex-col items-center justify-center gap-5 rounded-[22px] border border-dashed border-[#bdcdb9] bg-[#f7f8f1] p-6 text-center">
                <span className="block h-20 w-20 overflow-hidden rounded-2xl bg-[#e8f0e5]">{photoReady ? <SamplePortrait variant={sampleCharacter} sizes="80px" /> : <Camera size={32} className="m-6 text-[#578161]" />}</span><span><strong className="block text-sm">{photoReady ? "샘플 사진 등록 완료" : "샘플 사진 표시하기"}</strong><small className="mt-2 block text-[#737d74]">정면 · 밝은 조명 · 클릭하면 샘플 상태 전환</small></span>
              </button>
              <div className="mt-7 flex justify-end"><PreviewButton onClick={() => navigate("compose")}>메시지 작성 화면 <ArrowRight size={16} /></PreviewButton></div>
              </div>
            </div>
          </>}

          {screen === "compose" && <>
            {heading("WRITE YOUR HEART", "어떤 이야기를 전할까요?", "샘플 문구를 선택하거나 자유롭게 입력해 보세요. 입력은 현재 화면의 메모리에서만 유지됩니다.")}
            <PreviewCard>
              <div className="grid items-start gap-6 lg:grid-cols-[1.5fr_1fr]">
                <div><h2 className="text-2xl font-bold">오늘의 마음을 적어 보세요</h2><p className="mt-2 text-sm text-[#737d74]">받는 분: 어머니 · 샘플</p>
                  <div className="my-5 flex flex-wrap gap-2">{(Object.keys(TOPICS) as (keyof typeof TOPICS)[]).map((key) => <button type="button" key={key} aria-pressed={topic === key} onClick={() => { setTopic(key); setMessage(TOPICS[key]); }} className={`rounded-full border px-4 py-2 text-sm ${topic === key ? "border-[#315d4b] bg-[#315d4b] font-semibold text-white" : "border-[#e5eadf] bg-[#fafbf7] text-[#809074]"}`}>{key === "안부" ? "💌" : key === "건강" ? "🍀" : "🎂"} {key}</button>)}</div>
                  <label htmlFor="preview-message" className="mb-3 block text-sm font-bold">영상 편지 내용 · 샘플 입력</label>
                  <div className="overflow-hidden rounded-2xl border border-[#e3e8da]"><textarea id="preview-message" value={message} onChange={(event) => { setMessage(event.target.value); setReviewReady(false); }} maxLength={220} rows={6} className="block w-full resize-y bg-[#fafbf7] p-5 text-base leading-9 text-[#3e5541] focus:outline focus:outline-2 focus:outline-[#6c957c]" /><p className="border-t border-[#e5e8e1] bg-[#fafbf8] px-4 py-3 text-right text-xs text-[#737d74]">{message.length} / 220</p></div>
                  <p className="mt-4 rounded-xl bg-[#f7f9f4] p-4 text-xs leading-6 text-[#647b67]">대본 생성 API는 연결하지 않았습니다. 아래 버튼은 입력한 문구를 프리뷰 화면에 표시합니다.</p>
                </div>
                <LetterCompanion recipient="어머니" example={message} />
              </div>
              <div className="mt-7 flex flex-wrap justify-between gap-3"><PreviewButton secondary onClick={() => navigate("register")}><ArrowLeft size={16} /> 이전</PreviewButton><PreviewButton disabled={!message.trim()} onClick={() => { setReviewReady(false); navigate("review"); }}>영상 화면 미리보기 <ArrowRight size={16} /></PreviewButton></div>
            </PreviewCard>
          </>}

          {screen === "review" && <>
            {heading("PREVIEW & APPROVE", "영상을 확인하고 마음을 전해요", "실제 영상 대신 샘플 캐릭터와 입력한 문구를 표시합니다. AI 생성·재생·발송은 하지 않습니다.")}
            <PreviewCard>
              <div className="grid gap-7 md:grid-cols-2">
                <div className="relative aspect-square overflow-hidden rounded-2xl bg-[#eadbc8]"><SamplePortrait variant={sampleCharacter} /><span className="absolute left-4 top-4 rounded-md bg-[#283e30] px-3 py-1 text-xs text-white">정적 샘플 · 실제 영상 아님</span><span className="absolute inset-0 m-auto flex h-16 w-16 items-center justify-center rounded-full bg-white/90 text-[#315d4b]" aria-hidden="true"><Play size={28} /></span></div>
                <div className="flex flex-col justify-center"><h2 className="text-2xl font-bold">{reviewReady ? "샘플 미리보기 준비 완료 💚" : "영상 편지 미리보기"}</h2><p className="my-3 text-sm text-[#737d74]">받는 분: 어머니 · 샘플 데이터</p><div className="rounded-2xl border border-[#e5e9e2] bg-[#f9fbf8] p-5"><p className="mb-3 text-xs font-bold text-[#60896c]">{reviewReady ? "준비 완료 상태 · 샘플" : "생성 대기 상태 · 샘플"}</p><blockquote className="whitespace-pre-wrap break-words text-sm leading-8">{message}</blockquote></div><ul className="my-5 space-y-3 text-sm text-[#647568]"><li className="flex gap-2"><Check size={18} /> 대본 확인 화면</li><li className="flex gap-2"><ShieldCheck size={18} /> 전송 전 최종 승인 화면</li></ul><PreviewButton onClick={() => setReviewReady(!reviewReady)}><Sparkles size={16} />{reviewReady ? "대기 상태 보기" : "준비 완료 상태 보기"}</PreviewButton><div className="mt-3"><PreviewButton secondary className="w-full" onClick={() => navigate("watch")}>부모님 시청 화면 보기 <ArrowRight size={16} /></PreviewButton></div><button type="button" onClick={() => navigate("compose")} className="mt-4 text-sm font-bold text-[#60896c]">대본 수정 화면으로</button></div>
              </div>
            </PreviewCard>
          </>}

          {screen === "watch" && <>
            {heading("PARENT EXPERIENCE", "부모님 시청 화면", "부모님이 링크를 열었을 때의 화면 구성입니다. 실제 공유 링크나 시청 기록은 생성하지 않습니다.")}
            <div className="grid items-center gap-8 xl:grid-cols-[1fr_370px]">
              <div><p className="text-xs font-bold tracking-widest text-[#b77560]">FOR FAMILY 💌</p><h2 className="my-4 text-4xl font-extrabold leading-snug tracking-tighter">받는 순간부터<br />쉽고, 따뜻하게.</h2><p className="max-w-md text-sm leading-8 text-[#737d74]">큰 버튼과 읽기 편한 자막으로 마음을 전합니다. 반응을 눌러도 현재 프리뷰에만 표시됩니다.</p><p className="mt-6 flex items-center gap-3 text-sm font-bold text-[#60896c]"><MonitorPlay size={22} /> 큰 화면과 선명한 한국어 자막</p><p className="mt-4 flex items-center gap-3 text-sm font-bold text-[#60896c]"><Heart size={22} /> 한 번의 터치로 전하는 마음</p></div>
              <div className="mx-auto w-full max-w-[370px] rounded-[35px] bg-[#282d2a] p-2.5 shadow-xl"><div className="overflow-hidden rounded-[27px] bg-[#fff8ef]"><div className="flex items-center justify-between border-b border-[#e9e4d9] px-5 py-4"><strong className="text-xl text-[#315d4b]">♥ 온기</strong><span className="text-xs text-[#81786a]">샘플 시청 화면</span></div><div className="p-5"><p className="text-center text-xs text-[#81786a]">💌 지민이가 보낸 특별한 선물 · 샘플</p><h3 className="my-4 text-center text-2xl font-extrabold">엄마, 오늘도 사랑해요</h3><div className="relative aspect-[4/4.2] overflow-hidden rounded-2xl"><SamplePortrait variant={sampleCharacter} /><span className="absolute left-3 top-3 rounded bg-[#283e30] px-2 py-1 text-[11px] text-white">샘플 캐릭터</span><p className="absolute inset-x-3 bottom-3 max-h-40 overflow-y-auto whitespace-pre-wrap break-words rounded-lg bg-[#1c322a]/90 p-3 text-center text-base font-bold leading-7 text-white">{watching ? message : "영상 편지가 도착했어요. · 샘플"}</p></div><PreviewButton className="mt-4 w-full !text-base" onClick={() => setWatching(!watching)}><Play size={20} />{watching ? "시작 화면 보기" : "샘플 자막 보기"}</PreviewButton><p className="mb-3 mt-5 text-center text-sm text-[#81786a]">마음을 전해 보세요 · 샘플 반응</p><div className="flex gap-2">{["❤️", "🥰", "👍"].map((emoji) => <button key={emoji} type="button" aria-label={`${emoji} 샘플 반응`} aria-pressed={reaction === emoji} onClick={() => { setReaction(emoji); setNotice(`샘플 반응 ${emoji} 선택 · 전송하거나 저장하지 않았습니다.`); }} className={`min-h-14 flex-1 rounded-xl border text-2xl ${reaction === emoji ? "border-[#efb39b] bg-[#fff0e7]" : "border-[#e7e5dd] bg-white"}`}>{emoji}</button>)}</div></div></div></div>
            </div>
          </>}
          <p role="status" aria-live="polite" className="mt-6 text-center text-sm text-[#315d4b]">{notice}</p>
          <footer className="mt-9 border-t border-[#e8e9e2] pt-6 text-center text-xs leading-6 text-[#737d74]">온기 · 개발 전용 디자인 프리뷰 · 모든 인물·편지·상태는 샘플 데이터입니다.<br />새로고침하면 입력과 선택이 초기화됩니다. 실제 서비스는 기존 경로에서 별도로 동작합니다.</footer>
        </main>
      </div>
    </div>
  );
}
