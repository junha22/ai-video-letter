"use client";

import { useEffect, useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";

const WEEKDAYS = ["일", "월", "화", "수", "목", "금", "토"];

function addMonth(month: string, delta: number): string {
  const [year, value] = month.split("-").map(Number);
  const index = year * 12 + value - 1 + delta;
  return `${Math.floor(index / 12)}-${String(index % 12 + 1).padStart(2, "0")}`;
}

const SIZE = {
  normal: { box: "rounded-xl p-2.5", nav: "h-8 w-8 rounded-lg", icon: 15, title: "text-xs", week: "text-[10px]", weekCell: "py-1", day: "h-8 w-8 text-[11px]", dot: "bottom-1", note: "text-[10px]" },
  // 시니어 화면: 글씨와 누르는 곳을 크게
  // 휴대폰 폭(375px)에서도 7칸이 들어가도록 날짜 칸은 40px부터
  large: { box: "rounded-2xl p-3 sm:p-4", nav: "h-12 w-12 rounded-xl", icon: 24, title: "text-xl", week: "text-base", weekCell: "py-2", day: "h-10 w-10 text-lg sm:h-12 sm:w-12", dot: "bottom-1", note: "text-base" },
};

/** 날짜로 찾기 달력. 대화가 있는 날만 누를 수 있다 */
export function ChatCalendar({ activeDays, selected, today, onSelect, large = false }: {
  activeDays: string[];
  selected: string | null;
  today: string;
  onSelect: (date: string) => void;
  large?: boolean;
}) {
  const z = SIZE[large ? "large" : "normal"];
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
    <div className={`border border-[#ead9cd] bg-[#fff5eb] ${z.box}`}>
      <div className="flex items-center justify-between">
        <button type="button" onClick={() => setMonth(addMonth(month, -1))} disabled={month <= first} aria-label="이전 달" className={`inline-flex items-center justify-center text-[#81645d] hover:bg-[#fff5eb] disabled:opacity-30 ${z.nav}`}><ChevronLeft size={z.icon} /></button>
        <p className={`font-bold text-[#81645d] ${z.title}`} aria-live="polite">{year}년 {value}월</p>
        <button type="button" onClick={() => setMonth(addMonth(month, 1))} disabled={month >= last} aria-label="다음 달" className={`inline-flex items-center justify-center text-[#81645d] hover:bg-[#fff5eb] disabled:opacity-30 ${z.nav}`}><ChevronRight size={z.icon} /></button>
      </div>
      <div className={`mt-1 grid grid-cols-7 text-center text-[#81645d] ${z.week}`} aria-hidden="true">{WEEKDAYS.map((day) => <span key={day} className={z.weekCell}>{day}</span>)}</div>
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
              className={`relative mx-auto flex items-center justify-center rounded-full ${z.day} ${
                selected === day ? "bg-[#c8493c] font-bold text-white"
                  : enabled ? "font-bold text-[#c8493c] hover:bg-[#ead9cd]"
                    : "cursor-default text-stone-300"
              } ${day === today && selected !== day ? "ring-1 ring-[#b68e7e]" : ""}`}
            >
              {Number(day.slice(8))}
              {enabled && selected !== day && <span className={`absolute h-1 w-1 rounded-full bg-[#81645d] ${z.dot}`} aria-hidden="true" />}
            </button>
          );
        })}
      </div>
      <p className={`mt-2 text-center text-stone-400 ${z.note}`}>{chatDays ? `이달에 대화한 날 ${chatDays}일` : "이달에는 대화가 없어요"}</p>
    </div>
  );
}
