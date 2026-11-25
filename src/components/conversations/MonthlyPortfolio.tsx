"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Check, Clipboard, Download, FileText, RefreshCw, Sparkles } from "lucide-react";
import { api, errorText } from "@/lib/api";
import { formatConversationMonth, kstMonth, portfolioAsText, type MonthlyPortfolioResponse } from "@/lib/conversations";
import { Button, Card, Notice, Spinner } from "@/components/ui";
import { MonthCalendar } from "./MonthCalendar";
import { MonthChanges } from "./MonthChanges";

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
  const calendar = current?.calendar ?? [];
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
      <Card className="!border-[#ead9cd] !bg-[#fff5eb] sm:p-7">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div><h2 className="flex items-center gap-2 text-lg font-bold text-[#c8493c]"><FileText size={20} />한 달의 이야기</h2><p className="mt-2 max-w-xl text-sm leading-7 text-[#81645d]">{recipientName} 님이 남긴 한 달치 답글을 날짜별로 모아 한 장으로 정리해요. 답글이 쌓이는 중에도 작성할 수 있어요.</p></div>
          <label className="text-xs font-semibold text-[#81645d]">분석할 달<input type="month" aria-label="포트폴리오 분석할 달" value={month} max={kstMonth()} disabled={generating} onChange={(e) => { if (/^\d{4}-\d{2}$/.test(e.target.value)) setMonth(e.target.value); }} className="mt-2 block min-h-11 rounded-xl border border-[#ead9cd] bg-white px-4 text-sm text-[#c8493c] outline-none focus:ring-2 focus:ring-[#b68e7e]" /></label>
        </div>
        <div className="mt-5 flex flex-wrap items-center gap-3"><Button loading={generating} disabled={!current || current.reply_count === 0 || loading} onClick={() => { void load(true); }}><Sparkles size={17} />{portfolio ? "다시 분석하기" : "포트폴리오 작성"}</Button><button type="button" onClick={() => { void load(); }} disabled={loading || generating} className="inline-flex min-h-11 items-center gap-2 rounded-xl px-3 text-xs font-semibold text-[#81645d] disabled:opacity-50"><RefreshCw size={14} className={loading ? "animate-spin" : ""} />답글 현황 새로고침</button></div>
        {current && <p className="mt-4 text-xs leading-6 text-[#81645d]">이번 달 답글 {current.reply_count}개 · 대화한 날 {current.active_days}일{month === kstMonth() ? " · 이번 달은 아직 진행 중이에요." : ""}</p>}
      </Card>

      {data?.recipient_id === recipientId && data.available_months.length > 0 && <div><p className="mb-2 text-xs font-semibold text-stone-500">월별 기록</p><div className="flex flex-wrap gap-2">{data.available_months.map((item) => <button key={item} type="button" disabled={generating} onClick={() => setMonth(item)} aria-pressed={month === item} className={`min-h-10 rounded-full border px-4 text-xs font-semibold ${month === item ? "border-[#c8493c] bg-[#c8493c] text-white" : "border-[#ead9cd] bg-white text-stone-500 hover:border-[#b68e7e]"}`}>{formatConversationMonth(item)}</button>)}</div></div>}

      {error && <div role="alert"><Notice tone="error">{error}</Notice></div>}
      {loading && !current && <Spinner label="한 달의 답글을 불러오고 있어요" />}

      {/* 포트폴리오 제목 카드: 월별 기록 바로 아래 (작성 전이면 작성 안내) */}
      {portfolio && current && <Card className="sm:p-7"><div className="flex flex-wrap items-start justify-between gap-4"><div><p className="text-xs font-semibold text-[#a17e67]">{formatConversationMonth(month)} · {recipientName}</p><h3 className="mt-2 text-2xl font-bold text-[#c8493c]">{portfolio.title}</h3></div><div className="flex flex-wrap gap-2"><Button variant="secondary" onClick={() => { void copy(); }} className="!min-h-10 !px-3 !py-2 !text-xs">{copied ? <Check size={15} /> : <Clipboard size={15} />}{copied ? "복사했어요" : "내용 복사"}</Button><Button variant="secondary" onClick={download} className="!min-h-10 !px-3 !py-2 !text-xs"><Download size={15} />파일로 저장</Button></div></div>
        <p className="mt-5 whitespace-pre-wrap text-sm leading-8 text-stone-600">{portfolio.summary}</p>
        <div className="mt-6 grid grid-cols-2 gap-3"><Metric title="누적 답글" value={`${portfolio.reply_count}개`} /><Metric title="대화를 나눈 날" value={`${portfolio.active_days}일`} /></div>
        <p className="mt-5 text-xs text-stone-400">작성 {new Intl.DateTimeFormat("ko-KR", { timeZone: "Asia/Seoul", dateStyle: "medium", timeStyle: "short" }).format(new Date(portfolio.generated_at))} · 답글에 근거한 요약</p>
      </Card>}
      {current && !portfolio && <Card className="py-12 text-center"><FileText size={34} className="mx-auto text-[#81645d]" /><h3 className="mt-4 font-bold">{current.reply_count ? "쌓인 답글을 한 장의 기록으로" : "아직 이달의 답글이 없어요"}</h3><p className="mx-auto mt-3 max-w-md text-sm leading-7 text-stone-500">{current.reply_count ? "위의 ‘포트폴리오 작성’을 누르면 이달의 답글을 한 장으로 정리해서 내용 복사·파일로 저장할 수 있어요." : "영상 편지를 보내고 답글을 받아 보세요. 첫 답글부터 월간 기록에 차곡차곡 쌓여요."}</p></Card>}
      {current?.stale && <Notice>포트폴리오 작성 후 새 답글이 쌓였어요. 다시 분석하면 최신 답글까지 반영돼요.</Notice>}

      {/* 답장 살펴보기를 켠 방: AI 정리 + 위험도 캘린더 + 나눈 이야기. 꺼진 방: 답장 수 캘린더만. 둘 다 볼 때마다 계산해서 '포트폴리오 작성' 전에도 보인다 */}
      {current?.analysis_trends
        ? <MonthChanges recipientId={recipientId} trends={current.analysis_trends} counts={calendar} onOpenDate={onOpenDate}
          onTrends={(trends) => setData((old) => old && old.month === trends.month ? { ...old, analysis_trends: trends } : old)} />
        : current && calendar.length > 0 && <Card className="sm:p-7"><section aria-label="한 달 흐름">
          <h3 className="text-lg font-bold text-[#493035]">한 달 흐름</h3>
          <p className="mt-1 text-xs leading-6 text-stone-500">날짜를 누르면 그날 대화로 가요.</p>
          <div className="mt-4"><MonthCalendar month={month} counts={calendar} onOpenDate={onOpenDate} /></div>
        </section></Card>}

      {portfolio && current && <div className="rounded-2xl border border-[#ead9cd] bg-white/60 px-5 py-4 text-xs leading-7 text-stone-500"><p>이 기록은 상대가 직접 남긴 답글만 정리하며, 건강 상태나 심리 상태를 진단하지 않아요.</p>{portfolio.caveats.length > 0 && <ul className="mt-2 list-inside list-disc">{portfolio.caveats.map((text, index) => <li key={index}>{text}</li>)}</ul>}</div>}
      <p role="status" className="sr-only">{copied ? "포트폴리오를 클립보드에 복사했어요." : ""}</p>
    </div>
  );
}

function Metric({ title, value }: { title: string; value: string }) {
  return <div className="rounded-2xl bg-[#fff5eb] px-5 py-4"><p className="text-xs text-[#81645d]">{title}</p><p className="mt-2 text-xl font-bold text-[#81645d]">{value}</p></div>;
}
