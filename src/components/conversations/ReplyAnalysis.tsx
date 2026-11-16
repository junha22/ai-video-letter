"use client";

import { useState } from "react";
import { AlertTriangle, Loader2, RefreshCw, Sparkles } from "lucide-react";
import { Button, Card, Notice } from "@/components/ui";
import { api, errorText } from "@/lib/api";
import type { ReplyAnalysisCard, ReplyAnalysisState } from "@/lib/conversations";

// 수준 배지 색 (reply_analysis.LEVEL_UI와 같은 색)
export const LEVEL_TONE: Record<string, { bg: string; fg: string }> = {
  "없음": { bg: "#E4EEEC", fg: "#255F5A" },
  "살펴보기": { bg: "#FBE9CC", fg: "#7A4A00" },
  "바로 연락 필요": { bg: "#A8321E", fg: "#FFFFFF" },
};

/** 답장 아래 분석 카드. 문구는 서버가 정한 그대로 보여 준다 (진단처럼 들리지 않게) */
export function ReplyAnalysisView({ analysis, onRetry, retrying }: { analysis: ReplyAnalysisCard; onRetry?: () => void; retrying?: boolean }) {
  if (analysis.status !== "done") {
    const pending = analysis.status === "queued" || analysis.status === "running";
    return <div className={`mt-2 rounded-2xl border px-4 py-3 text-xs leading-6 ${pending ? "border-[#e1e6d9] bg-white text-stone-500" : "border-dashed border-[#d9cfc3] bg-white text-[#6b625a]"}`}>
      <p className="flex items-center gap-2">{pending ? <Loader2 size={14} className="animate-spin text-[#8aa07f]" /> : <AlertTriangle size={14} className="text-[#b08a5b]" />}{analysis.message}</p>
      {analysis.can_retry && onRetry && <Button variant="secondary" loading={retrying} onClick={onRetry} className="mt-2 !min-h-9 !px-3 !text-xs"><RefreshCw size={13} />다시 정리하기</Button>}
    </div>;
  }
  const tone = LEVEL_TONE[analysis.level ?? "없음"];
  const urgent = analysis.level === "바로 연락 필요";
  return <section aria-label="AI가 정리한 답장" className={`mt-2 rounded-2xl border bg-white px-4 py-4 ${urgent ? "border-[#A8321E]" : "border-[#ece5dc]"}`}>
    <div className="flex flex-wrap items-center justify-between gap-2"><span className="flex items-center gap-1.5 text-[11px] font-semibold text-[#8b8076]"><Sparkles size={13} />AI가 정리한 답장</span><span className="rounded-full px-2.5 py-1 text-xs font-bold" style={{ background: tone.bg, color: tone.fg }}>{analysis.level_label}</span></div>
    {analysis.summary && <p className="mt-2 text-[15px] font-bold leading-7 text-[#2b2622]">{analysis.summary}</p>}
    <p className="mt-1 text-xs text-[#6b625a]">{analysis.mood_text}{analysis.unsure_text ? ` · ${analysis.unsure_text}` : ""}</p>
    {analysis.voice_text && <p className={`mt-2 text-xs ${analysis.voice_down ? "font-semibold text-[#A8321E]" : "text-[#2b2622]"}`}><b>목소리</b> · {analysis.voice_text}</p>}
    {analysis.mismatch_text && <p className="mt-2 rounded-xl bg-[#FBE9CC] px-3 py-2 text-xs font-semibold leading-6 text-[#5C3800]">{analysis.mismatch_text}</p>}
    {!!analysis.signals?.length && <div className="mt-3 rounded-xl border border-[#F3E3C7] bg-[#FFFBF3] px-3 py-2.5">
      <p className="text-xs font-bold text-[#2b2622]">확인해 볼 것</p>
      <div className="mt-1.5 flex flex-wrap gap-1.5">{analysis.signals.map((s) => <span key={s.area} className="rounded-full bg-[#FFF4E2] px-2.5 py-0.5 text-[11px] font-bold text-[#7A4A00]">{s.area} · {s.value}</span>)}</div>
      {analysis.evidence?.map((quote) => <p key={quote} className="mt-1.5 text-xs leading-6 text-[#4b433c]">“{quote}”</p>)}
    </div>}
    {!!analysis.trend_alerts?.length && <p className="mt-2 text-xs leading-6 text-[#2b2622]"><b>지난 답장과 비교</b> · {analysis.trend_alerts.join(" / ")}</p>}
    <p className="mt-3 border-t border-[#f1ece5] pt-2 text-[11px] leading-5 text-stone-400">{analysis.notice}</p>
  </section>;
}

/** 대상자별 답장 살펴보기 켜기·끄기 (서버 기능이 켜져 있을 때만 보인다) */
export function ReplyAnalysisSettings({ recipientId, recipientName, state, onChange }: { recipientId: number; recipientName: string; state: ReplyAnalysisState; onChange: (state: ReplyAnalysisState) => void }) {
  const [agree, setAgree] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const save = async (enabled: boolean) => {
    if (!enabled && !confirm("답장 살펴보기를 끌까요?\n지금까지 정리한 내용과 분석 알림을 지워요. 답장과 음성은 남아요.")) return;
    setSaving(true); setError(null);
    try {
      onChange(await api<ReplyAnalysisState>(`/api/recipients/${recipientId}/reply-analysis`, { method: "PUT", json: { enabled, agree } }));
      setAgree(false);
    } catch (e) { setError(errorText(e)); } finally { setSaving(false); }
  };
  return <Card className="mt-6 !border-[#cfdcc7] sm:p-7"><div id="reply-analysis-settings">
    <h2 className="flex items-center gap-2 text-lg font-bold text-[#315d4b]"><Sparkles size={18} />답장 살펴보기 (AI)</h2>
    <p className="mt-3 text-sm leading-7 text-stone-600">{recipientName}의 답장(글·음성)을 AI가 정리해서 지금 알아야 할 일이 있는지 이 화면에만 보여 드려요. 진단이 아니에요. 켜면 {recipientName}의 대화방에 <b>말로 답하기</b> 버튼이 생기고, 처음 답장할 때 안내가 한 번 보여요.</p>
    {state.enabled
      ? <><p className="mt-4 text-sm font-semibold text-[#315d4b]">켜져 있어요 · {state.senior_notice ? `${recipientName}가 안내를 확인했어요` : `${recipientName}가 안내를 확인하면 정리를 시작해요`}</p><Button variant="secondary" loading={saving} onClick={() => { void save(false); }} className="mt-4 !text-sm">답장 살펴보기 끄기</Button></>
      : <><label className="mt-4 flex items-start gap-3 rounded-xl bg-[#f4f6ef] p-3 text-sm leading-7"><input type="checkbox" checked={agree} onChange={(e) => setAgree(e.target.checked)} className="mt-1.5 h-4 w-4 accent-[#315d4b]" /><span>{state.consent_text}</span></label><Button loading={saving} disabled={!agree} onClick={() => { void save(true); }} className="mt-4 !text-sm">답장 살펴보기 켜기</Button></>}
    {error && <div className="mt-4"><Notice tone="error">{error}</Notice></div>}
  </div></Card>;
}
