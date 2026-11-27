"use client";

import { CircleCheck, Mic } from "lucide-react";
import { formatConversationDate, kstDate, type AnalysisDay } from "@/lib/conversations";
import { LEVEL_TONE } from "./ReplyAnalysis";

const WEEKDAYS = ["일", "월", "화", "수", "목", "금", "토"];
export const PENDING_TONE = { bg: "#EFEAE4", fg: "#57514B" };  // 답장은 있지만 아직 정리 전이거나 정리하지 못한 날
export const RESOLVED_TONE = { bg: "#E3EAF6", fg: "#2F4C80" }; // 살펴볼 일이 뒤 답장에서 해결 완료로 확인된 날
const COUNT_TONE = { bg: "#FDE8DC", fg: "#A8402F" };          // 답장 살펴보기가 꺼진 방: 답장이 온 날
const LEGEND = [
  { label: "평소와 같아요", tone: LEVEL_TONE["없음"] },
  { label: "살펴보기", tone: LEVEL_TONE["살펴보기"] },
  { label: "바로 연락해 보세요", tone: LEVEL_TONE["바로 연락 필요"] },
  { label: "해결 완료", tone: RESOLVED_TONE },
  { label: "정리 전", tone: PENDING_TONE },
];

/** 한 달 흐름 캘린더. 숫자는 그날 답장 수.
 *  days가 있으면(답장 살펴보기를 켠 방) 그날 해결되지 않은 답장 중 가장 높은 수준의 색, 살펴볼 일이 모두 해결됐으면 해결 완료 색(✓).
 *  onPick이 있으면 날짜를 눌러 고르고(selected 테두리), 없으면 누르면 그날 대화로 간다 (꺼진 방).
 *  highlight가 있으면 그 날짜만 진하게, 나머지는 흐리게 (이야기 카드를 눌렀을 때) */
export function MonthCalendar({ month, counts, days, onOpenDate, onPick, selected, highlight }: {
  month: string;
  counts: { date: string; reply_count: number }[];
  days?: AnalysisDay[];
  onOpenDate: (date: string) => void;
  onPick?: (date: string) => void;
  selected?: string | null;
  highlight?: string[] | null;
}) {
  const [year, mon] = month.split("-").map(Number);
  const offset = new Date(Date.UTC(year, mon - 1, 1)).getUTCDay();
  const length = new Date(Date.UTC(year, mon, 0)).getUTCDate();
  const today = kstDate();
  const replies = new Map(counts.map((c) => [c.date, c.reply_count]));
  const analysis = new Map((days ?? []).map((d) => [d.date, d]));
  const bright = highlight ? new Set(highlight) : null;
  const dates = Array.from({ length }, (_, i) => `${month}-${String(i + 1).padStart(2, "0")}`);

  return <div>
    <div role="group" aria-label={`${year}년 ${mon}월 답장 캘린더`} className="grid max-w-md grid-cols-7 gap-1">
      {WEEKDAYS.map((name, i) => <div key={name} className={`pb-1 text-center text-[11px] font-semibold ${i === 0 ? "text-[#c8493c]" : "text-stone-400"}`}>{name}</div>)}
      {Array.from({ length: offset }, (_, i) => <div key={`empty-${i}`} aria-hidden="true" />)}
      {dates.map((date) => {
        const day = Number(date.slice(8));
        const count = replies.get(date) ?? 0;
        const isToday = date === today;
        if (!count) {
          return <div key={date}
            className={`flex aspect-square items-start justify-center rounded-lg pt-1 text-[11px] ${date > today ? "text-stone-300" : "text-stone-400"} ${isToday ? "ring-1 ring-[#c8493c]/50" : ""} ${bright ? "opacity-40" : ""}`}>{day}</div>;
        }
        const info = analysis.get(date);
        const tone = !days ? COUNT_TONE : info?.resolved ? RESOLVED_TONE : info?.level ? LEVEL_TONE[info.level] : PENDING_TONE;
        const voice = !!info && (info.voice_down || info.mismatch);
        const dim = !!bright && !bright.has(date);
        const label = [formatConversationDate(date), `답장 ${count}개`, info?.label,
          info?.any_resolved && !info.resolved ? "해결 완료된 답장 있음" : "",
          info?.mismatch ? "말과 목소리가 달랐던 답장 있음" : info?.voice_down ? "목소리가 평소보다 처진 답장 있음" : ""].filter(Boolean).join(" · ");
        return <button key={date} type="button" onClick={() => (onPick ? onPick(date) : onOpenDate(date))} aria-label={label} title={label}
          aria-pressed={onPick ? selected === date : undefined}
          className={`relative flex aspect-square flex-col items-center justify-between rounded-lg px-0.5 pb-1 pt-1 outline-none transition hover:scale-[1.04] focus-visible:ring-2 focus-visible:ring-[#c8493c] ${selected === date ? "ring-2 ring-[#3f3428]" : isToday ? "ring-2 ring-[#c8493c]/60" : ""} ${dim ? "opacity-20" : ""}`}
          style={{ background: tone.bg, color: tone.fg }}>
          <span className="text-[11px] font-semibold leading-none opacity-80">{day}</span>
          <span className="text-xs font-extrabold leading-none tabular-nums sm:text-sm">{count}<span className="text-[10px] font-bold">개</span></span>
          {(info?.resolved || info?.any_resolved) && <CircleCheck size={13} aria-hidden="true" className="absolute -left-1 -top-1 rounded-full bg-white text-[#2F4C80]" />}
          {voice && <Mic size={10} aria-hidden="true" className="absolute right-1 top-1" />}
        </button>;
      })}
    </div>
    {days
      ? <ul className="mt-3 flex flex-wrap gap-x-3 gap-y-1.5 text-[11px] text-stone-500">
        {LEGEND.map((item) => <li key={item.label} className="flex items-center gap-1.5"><span className="h-3 w-3 rounded" style={{ background: item.tone.bg }} />{item.label}</li>)}
        <li className="flex items-center gap-1"><CircleCheck size={11} className="text-[#2F4C80]" />해결 완료된 답장이 있는 날</li>
        <li className="flex items-center gap-1"><Mic size={11} />목소리가 평소보다 처진 날</li>
      </ul>
      : <p className="mt-3 text-[11px] text-stone-500">색칠한 날은 답장이 온 날이에요. 숫자는 그날 받은 답장 수예요.</p>}
  </div>;
}
