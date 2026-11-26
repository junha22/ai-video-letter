"use client";

import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import { ArrowRight, CircleCheck, Heart, HeartPulse, MessageCircle, Mic, RefreshCw, ShieldAlert, Sparkles, Sun, Users, type LucideIcon } from "lucide-react";
import { Button, Card } from "@/components/ui";
import { api, errorText } from "@/lib/api";
import { formatConversationMonth, type MonthAnalysisTrends, type ReplyLevel, type TopicStatus, type TrendReply } from "@/lib/conversations";
import { LEVEL_CHART, LevelDonut } from "./LevelDonut";
import { MonthCalendar, PENDING_TONE, RESOLVED_TONE } from "./MonthCalendar";
import { LEVEL_TONE } from "./ReplyAnalysis";

const shortDay = (date: string) => `${Number(date.slice(5, 7))}/${Number(date.slice(8))}`;
const dayTitle = (date: string) => {
  const [year, month, day] = date.split("-").map(Number);
  const weekday = new Intl.DateTimeFormat("ko-KR", { weekday: "short", timeZone: "UTC" }).format(new Date(Date.UTC(year, month - 1, day)));
  return `${month}월 ${day}일 (${weekday})`;
};
// 이번 달 나눈 이야기의 다섯 갈래 (reply_month.CATEGORIES)
const TOPIC_ICONS: Record<string, LucideIcon> = { "건강": HeartPulse, "마음·외로움": Heart, "생활·안전": ShieldAlert, "가족": Users, "일상": Sun };
// 갈래 상태 배지: 지금 신경 쓸 이야기가 먼저 오게 이 순서로 줄 세운다
const STATUS_ORDER: TopicStatus[] = ["이어지는 중", "나아지는 중", "해결 완료", "평소 이야기"];
const STATUS_STYLE: Record<TopicStatus, string> = {
  "이어지는 중": "bg-[#FBE9CC] text-[#7A4A00]",
  "나아지는 중": "bg-[#E4EEEC] text-[#255F5A]",
  "해결 완료": "bg-[#E3EAF6] text-[#2F4C80]",
  "평소 이야기": "border border-[#ece2d4] bg-white text-stone-500",
};
const LEVEL_LABEL: Record<ReplyLevel, string> = { "없음": "평소와 같아요", "살펴보기": "살펴보기", "바로 연락 필요": "바로 연락해 보세요" };
const toneOf = (level: ReplyLevel | null, resolved: boolean) => (resolved ? RESOLVED_TONE : level ? LEVEL_TONE[level] : PENDING_TONE);
const dotOf = (level: ReplyLevel | null, resolved: boolean) => (resolved ? LEVEL_CHART.resolved : level ? LEVEL_CHART[level] : LEVEL_CHART.pending);

/** 처음 열 때 보여 줄 날: 해결되지 않은 가장 높은 수준이 있는 날 중 가장 최근, 없으면 답장이 있는 가장 최근 날 */
function firstDay(trends: MonthAnalysisTrends): string | null {
  const days = [...trends.days].reverse();
  return days.find((d) => d.level === "바로 연락 필요")?.date ?? days.find((d) => d.level === "살펴보기")?.date ?? days[0]?.date ?? null;
}

/** 월간 포트폴리오의 'AI가 정리한 한 달의 변화'. 사실은 서버 규칙으로 세고, 정리 문장과 주제 묶음은 CLOVA가 한 번에 만든다
 *  (없거나 낡았으면 한 번 요청). counts는 캘린더의 날짜별 답장 수 (정리 전 답장도 센다) */
export function MonthChanges({ recipientId, trends, counts, onTrends, onOpenDate }: {
  recipientId: number;
  trends: MonthAnalysisTrends;
  counts: { date: string; reply_count: number }[];
  onTrends: (trends: MonthAnalysisTrends) => void;
  onOpenDate: (date: string) => void;
}) {
  const [summarizing, setSummarizing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [picked, setPicked] = useState<{ month: string; date: string } | null>(null);
  const [focusPick, setFocusPick] = useState<{ month: string; name: string } | null>(null);
  const tried = useRef(new Set<string>());
  const needsSummary = trends.can_summarize && (!trends.summary || trends.summary.stale);
  // 고른 날·이야기는 그 달에서만 (다른 달로 바꾸면 처음 보여 줄 날로)
  const day = picked?.month === trends.month && trends.days.some((d) => d.date === picked.date) ? picked.date : firstDay(trends);
  const focus = focusPick?.month === trends.month ? focusPick.name : null;
  const setFocus = (next: (old: string | null) => string | null) => {
    const name = next(focus);
    setFocusPick(name ? { month: trends.month, name } : null);
  };
  const topics = useMemo(() => [...(trends.topics ?? [])].sort((a, b) =>
    STATUS_ORDER.indexOf(a.status ?? "평소 이야기") - STATUS_ORDER.indexOf(b.status ?? "평소 이야기")), [trends.topics]);
  const focusDates = focus ? topics.find((topic) => topic.name === focus)?.dates ?? null : null;

  const summarize = async () => {
    setSummarizing(true); setError(null);
    try {
      onTrends(await api<MonthAnalysisTrends>(`/api/recipients/${recipientId}/portfolio/analysis-summary?month=${encodeURIComponent(trends.month)}`, { method: "POST" }));
    } catch (e) { setError(errorText(e)); } finally { setSummarizing(false); }
  };
  const summarizeRef = useRef(summarize);
  summarizeRef.current = summarize;

  // 포트폴리오를 열었을 때 정리 문장이 없거나 새 답장으로 낡았으면 한 번만 자동으로 만든다 (실패하면 버튼으로 다시)
  useEffect(() => {
    const key = `${trends.month}:${trends.summary?.generated_at ?? "none"}`;
    if (!needsSummary || tried.current.has(key)) return;
    tried.current.add(key);
    void summarizeRef.current();
  }, [needsSummary, trends.month, trends.summary?.generated_at]);

  return <Card className="!border-[#e7dccb] sm:p-7">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div><h3 className="flex items-center gap-2 text-lg font-bold text-[#6b4f35]"><Sparkles size={19} />AI가 정리한 한 달의 변화</h3><p className="mt-1 text-xs leading-6 text-stone-500">{formatConversationMonth(trends.month)} · 정리한 답장 {trends.analyzed}개 · {trends.notice}</p></div>
      {trends.can_summarize && trends.summary && !summarizing && <button type="button" onClick={() => { void summarize(); }} className="inline-flex min-h-9 items-center gap-1.5 rounded-xl px-2 text-xs font-semibold text-[#8b7a66] hover:bg-[#f6efe6]"><RefreshCw size={13} />다시 정리하기</button>}
    </div>

    <div className="mt-5 rounded-2xl bg-[#faf5ee] px-5 py-4">
      {summarizing ? <p className="flex items-center gap-2 text-sm text-[#8b7a66]"><RefreshCw size={15} className="animate-spin" />AI가 한 달을 정리하고 있어요…</p>
        : trends.summary ? <><p className="whitespace-pre-wrap text-[15px] leading-8 text-[#3f3428]">{trends.summary.text}</p>{trends.summary.stale && <p className="mt-2 text-xs text-[#a07850]">이 정리 뒤에 새 답장이 있어요. 다시 정리하면 반영돼요.</p>}</>
          : !trends.enough ? <p className="text-sm leading-7 text-stone-500">{trends.few_text}</p>
            : !trends.can_summarize ? <p className="text-sm leading-7 text-stone-500">CLOVA 키가 없어 한 달 정리 문장은 만들지 못했어요. 아래 흐름은 그대로 볼 수 있어요.</p>
              : <p className="text-sm text-stone-500">아직 한 달 정리가 없어요.</p>}
      {error && <div className="mt-3 flex flex-wrap items-center gap-2"><p role="alert" className="text-xs text-red-700">{error}</p><Button variant="secondary" onClick={() => { void summarize(); }} className="!min-h-9 !px-3 !text-xs">다시 정리하기</Button></div>}
    </div>

    {/* 한 달 흐름(캘린더 + 그날 답장) 옆에 이번 달 나눈 이야기: 카드를 누르면 바로 옆 캘린더에서 그 이야기의 날만 진하게 */}
    <div className="mt-6 grid gap-6 lg:grid-cols-[minmax(0,28rem)_minmax(0,1fr)] lg:items-start">
      {counts.length > 0 && <section aria-label="한 달 흐름" className="min-w-0">
        <h4 className="text-sm font-bold text-[#4a3d30]">한 달 흐름</h4>
        <p className="mt-1 text-xs text-stone-500">날마다 가장 살펴볼 답장의 색이에요. 숫자는 그날 답장 수, 날짜를 누르면 아래에 그날 답장이 보여요.</p>
        <div className="mt-3"><MonthCalendar month={trends.month} counts={counts} days={trends.days} onOpenDate={onOpenDate}
          onPick={(date) => setPicked({ month: trends.month, date })} selected={day} highlight={focusDates} /></div>
        {day && <DayReplies date={day} replies={trends.replies.filter((reply) => reply.date === day)} onOpenDate={onOpenDate} />}
      </section>}

      <section aria-label="이번 달 나눈 이야기" className="min-w-0">
        <h4 className="text-sm font-bold text-[#4a3d30]">이번 달 나눈 이야기</h4>
        {topics.length
          ? <>
            <ul className="mt-3 space-y-3">{topics.map((topic) => <li key={topic.name}>
              <TopicCard topic={topic} on={focus === topic.name} onToggle={() => setFocus((old) => (old === topic.name ? null : topic.name))} />
            </li>)}</ul>
            <p className="mt-2 text-[11px] leading-5 text-stone-400">AI가 답장 흐름을 읽고 갈래별 상태와 흐름을 정리했어요. 카드를 누르면 캘린더에서 그 이야기가 있던 날만 보여요.{trends.summary?.stale ? " 새 답장은 다시 정리하면 반영돼요." : ""}</p>
          </>
          : <p className="mt-2 text-xs leading-6 text-stone-500">{summarizing ? "AI가 이번 달 이야기를 갈래별로 나누고 있어요…"
            : !trends.enough ? trends.few_text
              : !trends.can_summarize ? "CLOVA 키가 없어 갈래별로 나누지 못했어요."
                : "아직 갈래별로 나누지 않았어요. 한 달 정리를 다시 하면 함께 나눠요."}</p>}
      </section>
    </div>

    <div className="mt-6 grid gap-6 lg:grid-cols-[minmax(0,28rem)_minmax(0,1fr)] lg:items-start">
      {trends.levels.some((level) => level.count > 0) && <section aria-label="이번 달 답장 상태" className="rounded-2xl bg-[#faf7f2] px-5 py-5">
        <h4 className="mb-4 text-sm font-bold text-[#4a3d30]">이번 달 답장 상태</h4>
        <LevelDonut levels={trends.levels} />
      </section>}

      <div className="grid content-start gap-5">
        <section aria-label="지난달과 비교">
          <h4 className="text-sm font-bold text-[#4a3d30]">지난달과 비교</h4>
          <table className="mt-2 w-full text-left text-xs"><thead><tr className="text-stone-500"><th className="py-1.5 font-semibold"></th><th className="py-1.5 font-semibold">{formatConversationMonth(trends.compare.prev_month)}</th><th className="py-1.5 font-semibold">{formatConversationMonth(trends.month)}</th></tr></thead>
            <tbody className="tabular-nums">{trends.compare.rows.map((row, index) => {
              const delta = row.now - row.prev;
              const first = row.group === "목소리" && trends.compare.rows[index - 1]?.group !== "목소리";
              return <Fragment key={`${row.group}-${row.label}`}>
                {first && <tr><td colSpan={3} className="pb-1 pt-4 text-[11px] font-bold text-[#8b7a66]"><span className="inline-flex items-center gap-1.5"><Mic size={12} />목소리 (평소 목소리와 비교한 음성 답장)</span></td></tr>}
                <tr className="border-t border-[#f0ebe4]">
                  <td className={`py-1.5 text-stone-600 ${row.group === "목소리" ? "pl-3" : ""}`}>{row.label}</td>
                  <td className="py-1.5 text-stone-500">{row.prev}{row.unit}</td>
                  <td className="py-1.5 font-semibold text-[#3f3428]">{row.now}{row.unit}{delta !== 0 && <span className="ml-1.5 text-[11px] font-normal text-stone-400">{delta > 0 ? `+${delta}` : `−${-delta}`}</span>}</td>
                </tr>
              </Fragment>;
            })}</tbody></table>
          {trends.compare.length_text && <p className="mt-2 text-xs text-stone-600">{trends.compare.length_text}</p>}
          {trends.compare.rows.some((row) => row.group === "목소리") && <p className="mt-2 text-[11px] leading-5 text-stone-400">목소리 줄은 평소 목소리를 기록한 뒤의 음성 답장만 세요. 목소리 크기는 휴대폰과의 거리에 따라서도 달라져요.</p>}
        </section>
      </div>
    </div>

    {trends.starters.length > 0 && <section aria-label="이번 달 이야기로 건넬 안부" className="mt-6 rounded-2xl bg-[#f7f2e9] px-5 py-4">
      <h4 className="text-sm font-bold text-[#826750]">이번 달 이야기로 건넬 안부</h4>
      <ul className="mt-2 space-y-1.5">{trends.starters.map((text) => <li key={text} className="text-sm leading-7 text-[#85715f]">· {text}</li>)}</ul>
    </section>}
  </Card>;
}

/** 캘린더에서 고른 날의 답장: 답장마다 단계(해결 완료 포함)·AI 한 줄 요약·갈래. 날짜 옆에는 단계·답장 수를 따로 쓰지 않는다 */
function DayReplies({ date, replies, onOpenDate }: { date: string; replies: TrendReply[]; onOpenDate: (date: string) => void }) {
  return <section aria-label={`${dayTitle(date)} 답장`} className="mt-4 rounded-2xl border border-[#ece2d4] bg-[#fbf8f3] px-4 py-3">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <h5 className="text-sm font-bold text-[#3f3428]">{dayTitle(date)}</h5>
      <button type="button" onClick={() => onOpenDate(date)} className="inline-flex min-h-8 items-center gap-1 rounded-lg px-1 text-xs font-semibold text-[#8a6a45] hover:text-[#c8493c]">그날 대화 보기<ArrowRight size={13} /></button>
    </div>
    <ul className="mt-2 space-y-2">{replies.map((reply) => {
      const tone = toneOf(reply.level, reply.resolved);
      const Icon = reply.topic ? TOPIC_ICONS[reply.topic] ?? MessageCircle : null;
      return <li key={reply.reply_id} className="flex items-start gap-2.5">
        <span className="mt-0.5 inline-flex shrink-0 items-center gap-1 whitespace-nowrap rounded-full px-2.5 py-0.5 text-[11px] font-bold" style={{ background: tone.bg, color: tone.fg }}>
          {reply.resolved && <CircleCheck size={11} aria-hidden="true" />}{reply.label}
        </span>
        <p className="min-w-0 flex-1 text-sm leading-6 text-[#3f3428]">
          {reply.summary ?? "아직 정리 중이에요."}
          {Icon && <span className="ml-1.5 inline-flex items-center gap-1 whitespace-nowrap rounded-full border border-[#ece2d4] bg-white px-2 align-[1px] text-[11px] font-semibold text-[#7a6a58]"><Icon size={11} aria-hidden="true" />{reply.topic}</span>}
          {reply.voice && <span className="ml-1 inline-flex items-center gap-1 whitespace-nowrap rounded-full border border-[#ece2d4] bg-white px-2 align-[1px] text-[11px] font-semibold text-[#7a6a58]"><Mic size={11} aria-hidden="true" />{reply.voice_down ? "목소리 처짐" : "음성"}</span>}
        </p>
      </li>;
    })}</ul>
  </section>;
}

/** 이번 달 나눈 이야기 카드: 갈래·답장 수·상태 배지(AI)와 흐름 단계 (날짜·짧은 이름, 점 색은 그 답장의 단계). 누르면 캘린더에서 그 이야기의 날만 강조 */
function TopicCard({ topic, on, onToggle }: { topic: NonNullable<MonthAnalysisTrends["topics"]>[number]; on: boolean; onToggle: () => void }) {
  const Icon = TOPIC_ICONS[topic.name] ?? MessageCircle;
  return <button type="button" onClick={onToggle} aria-pressed={on}
    className={`w-full rounded-xl border border-[#ece2d4] bg-[#fbf8f3] px-4 py-3 text-left outline-none transition hover:border-[#d9c7b2] focus-visible:ring-2 focus-visible:ring-[#c8493c] ${on ? "ring-2 ring-[#8a6a45]" : ""}`}>
    <span className="flex items-center gap-2">
      <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-white text-[#8a6a45]" aria-hidden="true"><Icon size={16} /></span>
      <span className="text-sm font-bold text-[#5b4632]">{topic.name}</span>
      <span className="text-xs font-semibold text-[#a08a72]">답장 {topic.count}개</span>
      {topic.status && <span className={`ml-auto inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2.5 py-0.5 text-[11px] font-bold ${STATUS_STYLE[topic.status]}`}>
        {topic.status === "해결 완료" && <CircleCheck size={11} aria-hidden="true" />}{topic.status}
      </span>}
    </span>
    {topic.steps.length > 0 && <ol className="mt-3 flex" aria-label={`${topic.name} 흐름`}>{topic.steps.map((step, index) => {
      const tone = toneOf(step.level, step.resolved);
      return <li key={`${step.date}-${index}`} className="relative flex min-w-0 flex-1 flex-col items-center gap-0.5 px-1 text-center">
        {index > 0 && <span className="absolute right-1/2 top-[6px] h-0.5 w-full bg-[#e3d6c6]" aria-hidden="true" />}
        <span className="relative h-3.5 w-3.5 rounded-full" style={{ background: tone.bg, border: `2px solid ${dotOf(step.level, step.resolved)}` }}
          title={step.resolved ? "해결 완료" : step.level ? LEVEL_LABEL[step.level] : "정리 전"} />
        <span className="text-[11px] font-bold tabular-nums text-[#5b4b3b]">{shortDay(step.date)}</span>
        <span className="text-[11px] leading-4 text-[#6b5a48]">{step.label}</span>
      </li>;
    })}</ol>}
  </button>;
}
