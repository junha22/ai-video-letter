"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowUpRight, Check, Clipboard, Download, FileText, RefreshCw, Sparkles } from "lucide-react";
import { api, errorText } from "@/lib/api";
import { formatConversationDate, formatConversationMonth, kstMonth, portfolioAsText, type MonthlyPortfolioResponse, type PortfolioEvidence } from "@/lib/conversations";
import { Button, Card, Notice, Spinner } from "@/components/ui";

export function MonthlyPortfolio({ recipientId, recipientName, onOpenDate }: {
  recipientId: number;
  recipientName: string;
  onOpenDate: (date: string) => void;
}) {
  const [month, setMonth] = useState(kstMonth());
  const [data, setData] = useState<MonthlyPortfolioResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const sequence = useRef(0);
  const requestBusy = useRef(false);

  const load = useCallback(async (generate = false, quiet = false) => {
    if (quiet && requestBusy.current) return;
    const request = ++sequence.current;
    requestBusy.current = true;
    if (generate) { setGenerating(true); setCopied(false); } else if (!quiet) setLoading(true);
    if (!quiet) setError(null);
    try {
      const next = await api<MonthlyPortfolioResponse>(`/api/recipients/${recipientId}/portfolio?month=${encodeURIComponent(month)}`, generate ? { method: "POST" } : {});
      if (request === sequence.current) { setData(next); setError(null); }
    } catch (e) {
      if (request === sequence.current) setError(errorText(e));
    } finally {
      if (request === sequence.current) { requestBusy.current = false; setLoading(false); setGenerating(false); }
    }
  }, [recipientId, month]);

  useEffect(() => {
    setCopied(false);
    void load();
    const refresh = () => { if (document.visibilityState === "visible") void load(false, true); };
    const timer = window.setInterval(refresh, 30000);
    window.addEventListener("focus", refresh);
    document.addEventListener("visibilitychange", refresh);
    return () => { sequence.current += 1; requestBusy.current = false; window.clearInterval(timer); window.removeEventListener("focus", refresh); document.removeEventListener("visibilitychange", refresh); };
  }, [load]);

  const current = data?.recipient_id === recipientId && data.month === month ? data : null;
  const portfolio = current?.portfolio;
  const reportText = current ? portfolioAsText(current, recipientName) : "";

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(reportText);
      setCopied(true);
    } catch {
      setError("복사하지 못했어요. ‘파일로 저장’을 이용해 주세요.");
    }
  };

  const download = () => {
    const url = URL.createObjectURL(new Blob(["\uFEFF", reportText], { type: "text/plain;charset=utf-8" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = `${recipientName.replace(/[\\/:*?"<>|]/g, "_")}_${month}_대화포트폴리오.txt`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  };

  return (
    <div className="space-y-6">
      <Card className="!border-[#dce6d5] !bg-[#f1f5ec] sm:p-7">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div><h2 className="flex items-center gap-2 text-lg font-bold text-[#315d4b]"><FileText size={20} />한 달의 이야기</h2><p className="mt-2 max-w-xl text-sm leading-7 text-[#728268]">{recipientName} 님이 남긴 한 달치 답글에서 자주 나눈 이야기와 기억할 말을 모아요. 답글이 쌓이는 중에도 작성할 수 있어요.</p></div>
          <label className="text-xs font-semibold text-[#536d54]">분석할 달<input type="month" aria-label="포트폴리오 분석할 달" value={month} max={kstMonth()} disabled={generating} onChange={(e) => { if (/^\d{4}-\d{2}$/.test(e.target.value)) setMonth(e.target.value); }} className="mt-2 block min-h-11 rounded-xl border border-[#cbd9c4] bg-white px-4 text-sm text-[#315d4b] outline-none focus:ring-2 focus:ring-[#a9bd9b]" /></label>
        </div>
        <div className="mt-5 flex flex-wrap items-center gap-3"><Button loading={generating} disabled={!current || current.reply_count === 0 || loading} onClick={() => { void load(true); }}><Sparkles size={17} />{portfolio ? "다시 분석하기" : "포트폴리오 작성"}</Button><button type="button" onClick={() => { void load(); }} disabled={loading || generating} className="inline-flex min-h-11 items-center gap-2 rounded-xl px-3 text-xs font-semibold text-[#6b7c62] disabled:opacity-50"><RefreshCw size={14} className={loading ? "animate-spin" : ""} />답글 현황 새로고침</button></div>
        {current && <p className="mt-4 text-xs leading-6 text-[#718168]">이번 달 답글 {current.reply_count}개 · 대화한 날 {current.active_days}일{month === kstMonth() ? " · 이번 달은 아직 진행 중이에요." : ""}</p>}
      </Card>

      {data?.recipient_id === recipientId && data.available_months.length > 0 && <div><p className="mb-2 text-xs font-semibold text-stone-500">월별 기록</p><div className="flex flex-wrap gap-2">{data.available_months.map((item) => <button key={item} type="button" disabled={generating} onClick={() => setMonth(item)} aria-pressed={month === item} className={`min-h-10 rounded-full border px-4 text-xs font-semibold ${month === item ? "border-[#315d4b] bg-[#315d4b] text-white" : "border-[#dfe5d8] bg-white text-stone-500 hover:border-[#a8bc9d]"}`}>{formatConversationMonth(item)}</button>)}</div></div>}

      {error && <div role="alert"><Notice tone="error">{error}</Notice></div>}
      {loading && !current && <Spinner label="한 달의 답글을 불러오고 있어요" />}
      {current?.stale && <Notice>포트폴리오 작성 후 새 답글이 쌓였어요. 다시 분석하면 최신 답글까지 반영돼요.</Notice>}
      {current && !portfolio && <Card className="py-12 text-center"><FileText size={34} className="mx-auto text-[#9aaf91]" /><h3 className="mt-4 font-bold">{current.reply_count ? "쌓인 답글을 한 장의 기록으로" : "아직 이달의 답글이 없어요"}</h3><p className="mx-auto mt-3 max-w-md text-sm leading-7 text-stone-500">{current.reply_count ? "위의 ‘포트폴리오 작성’을 누르면 관심 주제, 날짜별 대화 흐름, 다음에 건넬 안부를 확인할 수 있어요." : "영상 편지를 보내고 답글을 받아 보세요. 첫 답글부터 월간 기록에 차곡차곡 쌓여요."}</p></Card>}

      {portfolio && current && <article className="space-y-6" aria-label={`${formatConversationMonth(month)} 대화 포트폴리오`}>
        <Card className="sm:p-7"><div className="flex flex-wrap items-start justify-between gap-4"><div><p className="text-xs font-semibold text-[#a17e67]">{formatConversationMonth(month)} · {recipientName}</p><h3 className="mt-2 text-2xl font-bold text-[#315d4b]">{portfolio.title}</h3></div><div className="flex flex-wrap gap-2"><Button variant="secondary" onClick={() => { void copy(); }} className="!min-h-10 !px-3 !py-2 !text-xs">{copied ? <Check size={15} /> : <Clipboard size={15} />}{copied ? "복사했어요" : "내용 복사"}</Button><Button variant="secondary" onClick={download} className="!min-h-10 !px-3 !py-2 !text-xs"><Download size={15} />파일로 저장</Button></div></div>
          <p className="mt-5 whitespace-pre-wrap text-sm leading-8 text-stone-600">{portfolio.summary}</p>
          <div className="mt-6 grid grid-cols-2 gap-3 sm:grid-cols-3"><Metric title="누적 답글" value={`${portfolio.reply_count}개`} /><Metric title="대화를 나눈 날" value={`${portfolio.active_days}일`} /><Metric title="발견한 이야기" value={`${portfolio.topics.length}가지`} /></div>
          <p className="mt-5 text-xs text-stone-400">작성 {new Intl.DateTimeFormat("ko-KR", { timeZone: "Asia/Seoul", dateStyle: "medium", timeStyle: "short" }).format(new Date(portfolio.generated_at))} · 답글에 근거한 요약</p>
        </Card>

        <Card className="sm:p-7"><h3 className="text-lg font-bold text-[#3e5541]">자주 나눈 이야기</h3>{portfolio.topics.length === 0 ? <p className="mt-4 text-sm text-stone-500">주제를 분류할 만큼의 표현이 아직 모이지 않았어요.</p> : <ul className="mt-5 grid gap-4 md:grid-cols-2">{portfolio.topics.map((topic) => <li key={topic.name} className="rounded-2xl border border-[#e5eadf] p-5"><div className="flex justify-between gap-3"><h4 className="font-bold text-[#536d54]">{topic.name}</h4><span className="text-xs text-stone-500">답글 {topic.count}개</span></div><div className="mt-3 h-1.5 overflow-hidden rounded-full bg-[#edf2e7]" aria-hidden="true"><div className="h-full rounded-full bg-[#8da77d]" style={{ width: `${Math.min(100, topic.count / Math.max(1, portfolio.reply_count) * 100)}%` }} /></div><ul className="mt-4 space-y-3">{topic.evidence.map((item, index) => <li key={`${item.reply_id}-${index}`}><Evidence item={item} onOpenDate={onOpenDate} /></li>)}</ul></li>)}</ul>}</Card>

        <Card className="sm:p-7"><h3 className="text-lg font-bold text-[#3e5541]">날짜별 대화 흐름</h3><p className="mt-2 text-xs leading-6 text-stone-500">막대를 누르면 그날의 대화를 볼 수 있어요. 답글 수는 대화량을 나타내요.</p><div className="mt-6 overflow-x-auto pb-3"><div className="flex h-40 min-w-[540px] items-end gap-1.5" aria-label="날짜별 답글 수">{portfolio.daily_trends.map((day) => <button key={day.date} type="button" onClick={() => onOpenDate(day.date)} aria-label={`${formatConversationDate(day.date)}, 답글 ${day.reply_count}개`} title={`${day.date} · 답글 ${day.reply_count}개`} className="group flex h-full min-w-3 flex-1 flex-col justify-end rounded-md outline-none focus-visible:ring-2 focus-visible:ring-[#315d4b]"><span className="mb-1 text-center text-[9px] text-stone-500">{day.reply_count || ""}</span><span className={`block min-h-1 rounded-t-md transition-colors ${day.reply_count ? "bg-[#8da77d] group-hover:bg-[#587a49]" : "bg-[#e6ebdf]"}`} style={{ height: `${Math.max(3, day.reply_count / Math.max(1, ...portfolio.daily_trends.map((d) => d.reply_count)) * 100)}px` }} /><span className="mt-2 text-center text-[9px] text-stone-400">{Number(day.date.slice(8))}</span></button>)}</div></div><details className="mt-4 border-t border-[#edf0e8] pt-4"><summary className="cursor-pointer text-xs font-semibold text-[#6b8060]">날짜별 기록 자세히 보기</summary><div className="mt-4 overflow-x-auto"><table className="w-full text-left text-xs"><thead><tr className="border-b border-[#e3eadc] text-[#6b8060]"><th className="p-3 font-semibold">날짜</th><th className="p-3 font-semibold">답글</th><th className="p-3 font-semibold">이야기</th></tr></thead><tbody>{portfolio.daily_trends.map((day) => <tr key={day.date} className="border-b border-[#f0f2ec]"><td className="whitespace-nowrap p-3"><button type="button" onClick={() => onOpenDate(day.date)} className="min-h-8 font-semibold text-[#315d4b] underline underline-offset-4">{formatConversationDate(day.date)}</button></td><td className="p-3">{day.reply_count}개</td><td className="p-3 text-stone-500">{day.topics.join(", ") || "—"}</td></tr>)}</tbody></table></div></details></Card>

        {portfolio.representative_replies.length > 0 && <Card className="sm:p-7"><h3 className="text-lg font-bold text-[#3e5541]">기억하고 싶은 답글</h3><ul className="mt-5 grid gap-4 sm:grid-cols-2">{portfolio.representative_replies.map((item, index) => <li key={`${item.reply_id}-${index}`} className="rounded-2xl bg-[#faf8f2] p-5"><Evidence item={item} onOpenDate={onOpenDate} /></li>)}</ul></Card>}
        {portfolio.conversation_starters.length > 0 && <Card className="!bg-[#f7f2e9] sm:p-7"><h3 className="text-lg font-bold text-[#826750]">다음 안부에는 이런 말을</h3><ul className="mt-4 space-y-3">{portfolio.conversation_starters.map((text, index) => <li key={index} className="flex items-start gap-3 text-sm leading-7 text-[#85715f]"><span className="mt-1 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-white text-[10px] font-bold">{index + 1}</span>{text}</li>)}</ul></Card>}
        <div className="rounded-2xl border border-[#e4e7dc] bg-white/60 px-5 py-4 text-xs leading-7 text-stone-500"><p>이 기록은 상대가 직접 남긴 답글만 정리하며, 건강 상태나 심리 상태를 진단하지 않아요.</p>{portfolio.caveats.length > 0 && <ul className="mt-2 list-inside list-disc">{portfolio.caveats.map((text, index) => <li key={index}>{text}</li>)}</ul>}</div>
      </article>}
      <p role="status" className="sr-only">{copied ? "포트폴리오를 클립보드에 복사했어요." : ""}</p>
    </div>
  );
}

function Metric({ title, value }: { title: string; value: string }) {
  return <div className="rounded-2xl bg-[#f3f6ee] px-5 py-4"><p className="text-xs text-[#8c9b81]">{title}</p><p className="mt-2 text-xl font-bold text-[#4e6b46]">{value}</p></div>;
}

function Evidence({ item, onOpenDate }: { item: PortfolioEvidence; onOpenDate: (date: string) => void }) {
  return <blockquote><p className="whitespace-pre-wrap break-words text-sm leading-7 text-stone-600">“{item.text}”</p><button type="button" onClick={() => onOpenDate(item.date)} className="mt-2 inline-flex min-h-8 items-center gap-1 text-[11px] font-semibold text-[#8a9b7d] hover:text-[#315d4b]">{formatConversationDate(item.date)} 대화 보기<ArrowUpRight size={12} /></button></blockquote>;
}
