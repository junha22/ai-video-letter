"use client";

import { useEffect, useRef, useState } from "react";
import { RefreshCw, Sparkles } from "lucide-react";
import { Button, Card } from "@/components/ui";
import { api, errorText } from "@/lib/api";
import { formatConversationMonth, type MonthAnalysisTrends } from "@/lib/conversations";
import { MonthCalendar } from "./MonthCalendar";

const shortDay = (date: string) => `${Number(date.slice(5, 7))}/${Number(date.slice(8))}`;

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
  const tried = useRef(new Set<string>());
  const needsSummary = trends.can_summarize && (!trends.summary || trends.summary.stale);

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

    {counts.length > 0 && <section className="mt-6" aria-label="한 달 흐름">
      <h4 className="text-sm font-bold text-[#4a3d30]">한 달 흐름</h4>
      <p className="mt-1 text-xs text-stone-500">날마다 가장 살펴볼 답장의 색이에요. 숫자는 그날 답장 수, 누르면 그날 대화로 가요.</p>
      <div className="mt-3"><MonthCalendar month={trends.month} counts={counts} days={trends.days} onOpenDate={onOpenDate} /></div>
    </section>}

    <div className="mt-6 grid gap-5 lg:grid-cols-2">
      <section aria-label="이번 달 나눈 이야기" className="min-w-0">
        <h4 className="text-sm font-bold text-[#4a3d30]">이번 달 나눈 이야기</h4>
        {trends.topics?.length
          ? <>
            <ul className="mt-3 space-y-3">{trends.topics.map((topic) => <li key={topic.name} className="rounded-xl border border-[#ece2d4] bg-[#fbf8f3] px-4 py-3">
              <p className="text-sm font-bold text-[#5b4632]">{topic.name} <span className="font-semibold text-[#a08a72]">답장 {topic.count}개</span></p>
              <p className="mt-1 text-xs leading-6 text-[#4b433c]">{topic.summary}</p>
              <p className="mt-1 flex flex-wrap gap-x-2 text-xs">{topic.dates.map((date) => <button key={date} type="button" onClick={() => onOpenDate(date)} className="min-h-7 font-semibold text-[#8a6a45] underline underline-offset-2">{shortDay(date)}</button>)}</p>
            </li>)}</ul>
            <p className="mt-2 text-[11px] leading-5 text-stone-400">AI가 답장마다 정리한 내용을 주제별로 묶었어요.{trends.summary?.stale ? " 새 답장은 다시 정리하면 반영돼요." : ""}</p>
          </>
          : <p className="mt-2 text-xs leading-6 text-stone-500">{summarizing ? "AI가 이번 달 이야기를 주제별로 묶고 있어요…"
            : !trends.enough ? trends.few_text
              : !trends.can_summarize ? "CLOVA 키가 없어 주제별로 묶지 못했어요."
                : "아직 주제별로 묶지 않았어요. 한 달 정리를 다시 하면 함께 묶어요."}</p>}
      </section>

      <div className="grid content-start gap-5">
        {trends.voice && <section aria-label="목소리 흐름">
          <h4 className="text-sm font-bold text-[#4a3d30]">목소리 흐름</h4>
          <ol className="mt-3 flex flex-wrap gap-2">{trends.voice.points.map((point, index) => <li key={`${point.date}-${index}`} className={`rounded-lg px-2.5 py-1 text-xs ${point.state === "평소보다 처짐" ? "bg-[#fbe6e1] font-semibold text-[#A8321E]" : "bg-[#f1f3ee] text-stone-600"}`}><span className="tabular-nums">{shortDay(point.date)}</span> {point.state}</li>)}</ol>
          <p className="mt-2 text-xs leading-6 text-stone-500">평소보다 처진 답장 {trends.voice.down}번 · 말과 목소리가 다른 답장 {trends.voice.mismatch}번. 목소리 크기는 휴대폰과의 거리에 따라서도 달라져요.</p>
        </section>}

        <section aria-label="지난달과 비교">
          <h4 className="text-sm font-bold text-[#4a3d30]">지난달과 비교</h4>
          <table className="mt-2 w-full text-left text-xs"><thead><tr className="text-stone-500"><th className="py-1.5 font-semibold"></th><th className="py-1.5 font-semibold">{formatConversationMonth(trends.compare.prev_month)}</th><th className="py-1.5 font-semibold">{formatConversationMonth(trends.month)}</th></tr></thead>
            <tbody className="tabular-nums">{trends.compare.rows.map((row) => <tr key={row.label} className="border-t border-[#f0ebe4]"><td className="py-1.5 text-stone-600">{row.label}</td><td className="py-1.5 text-stone-500">{row.prev}{row.unit}</td><td className="py-1.5 font-semibold text-[#3f3428]">{row.now}{row.unit}</td></tr>)}</tbody></table>
          {trends.compare.length_text && <p className="mt-2 text-xs text-stone-600">{trends.compare.length_text}</p>}
        </section>
      </div>
    </div>

    {trends.starters.length > 0 && <section aria-label="이번 달 이야기로 건넬 안부" className="mt-6 rounded-2xl bg-[#f7f2e9] px-5 py-4">
      <h4 className="text-sm font-bold text-[#826750]">이번 달 이야기로 건넬 안부</h4>
      <ul className="mt-2 space-y-1.5">{trends.starters.map((text) => <li key={text} className="text-sm leading-7 text-[#85715f]">· {text}</li>)}</ul>
    </section>}
  </Card>;
}
