"use client";

import { useEffect, useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";

const WEEKDAYS = ["일", "월", "화", "수", "목", "금", "토"];

function addMonth(month: string, delta: number): string {
  const [year, value] = month.split("-").map(Number);
  const index = year * 12 + value - 1 + delta;
  return `${Math.floor(index / 12)}-${String(index % 12 + 1).padStart(2, "0")}`;
}

/** 날짜로 찾기 달력. 대화가 있는 날만 누를 수 있다 */
export function ChatCalendar({ activeDays, selected, today, onSelect }: {
  activeDays: string[];
  selected: string | null;
  today: string;
  onSelect: (date: string) => void;
}) {
  const active = new Set(activeDays);
  const first = activeDays.length ? activeDays.reduce((a, b) => (a < b ? a : b)).slice(0, 7) : today.slice(0, 7);
  const last = today.slice(0, 7);
  const [month, setMonth] = useState((selected ?? activeDays[0] ?? today).slice(0, 7));
  // 고른 날짜가 바뀌면 그 달을 보여 준다
  useEffect(() => { if (selected) setMonth(selected.slice(0, 7)); }, [selected]);

  const [year, value] = month.split("-").map(Number);
  const offset = new Date(Date.UTC(year, value - 1, 1)).getUTCDay();
  const length = new Date(Date.UTC(year, value, 0)).getUTCDate();
  const cells = [...Array<null>(offset).fill(null), ...Array.from({ length }, (_, i) => `${month}-${String(i + 1).padStart(2, "0")}`)];
  const chatDays = activeDays.filter((day) => day.startsWith(month)).length;

  return (
    <div className="rounded-xl border border-[#e4e9dc] bg-[#fcfdf9] p-2.5">
      <div className="flex items-center justify-between">
        <button type="button" onClick={() => setMonth(addMonth(month, -1))} disabled={month <= first} aria-label="이전 달" className="inline-flex h-8 w-8 items-center justify-center rounded-lg text-[#6f865f] hover:bg-[#eef3e8] disabled:opacity-30"><ChevronLeft size={15} /></button>
        <p className="text-xs font-bold text-[#4d6546]" aria-live="polite">{year}년 {value}월</p>
        <button type="button" onClick={() => setMonth(addMonth(month, 1))} disabled={month >= last} aria-label="다음 달" className="inline-flex h-8 w-8 items-center justify-center rounded-lg text-[#6f865f] hover:bg-[#eef3e8] disabled:opacity-30"><ChevronRight size={15} /></button>
      </div>
      <div className="mt-1 grid grid-cols-7 text-center text-[10px] text-[#a0ad94]" aria-hidden="true">{WEEKDAYS.map((day) => <span key={day} className="py-1">{day}</span>)}</div>
      <div className="grid grid-cols-7 gap-y-0.5 text-center">
        {cells.map((day, index) => {
          if (!day) return <span key={`blank-${index}`} />;
          const enabled = active.has(day);
          const label = `${value}월 ${Number(day.slice(8))}일`;
          return (
            <button
              key={day}
              type="button"
              disabled={!enabled}
              onClick={() => onSelect(day)}
              aria-pressed={selected === day}
              aria-label={enabled ? `${label} 대화 보기` : `${label} 대화 없음`}
              className={`relative mx-auto flex h-8 w-8 items-center justify-center rounded-full text-[11px] ${
                selected === day ? "bg-[#315d4b] font-bold text-white"
                  : enabled ? "font-bold text-[#315d4b] hover:bg-[#e6eedf]"
                    : "cursor-default text-stone-300"
              } ${day === today && selected !== day ? "ring-1 ring-[#aabc9c]" : ""}`}
            >
              {Number(day.slice(8))}
              {enabled && selected !== day && <span className="absolute bottom-1 h-1 w-1 rounded-full bg-[#8da77d]" aria-hidden="true" />}
            </button>
          );
        })}
      </div>
      <p className="mt-2 text-center text-[10px] text-stone-400">{chatDays ? `이달에 대화한 날 ${chatDays}일` : "이달에는 대화가 없어요"}</p>
    </div>
  );
}
