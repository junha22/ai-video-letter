"use client";

import { useState } from "react";
import type { MonthAnalysisTrends } from "@/lib/conversations";

/** 원형 그래프의 상태 색. 캘린더 칸 색과 같은 색 계열을 진하게 한 것 (dataviz 팔레트 검사 통과: 명도·채도·색약 구분).
 *  살펴보기 주황은 흰 바탕 대비가 낮아서 옆 목록에 이름·수·비율을 늘 같이 쓴다 (색만으로 읽지 않게) */
export const LEVEL_CHART: Record<string, string> = {
  "없음": "#2A9D8F",
  "살펴보기": "#E09B2D",
  "바로 연락 필요": "#A8321E",
  resolved: "#4C6FB0", // 해결 완료 (네 색 모두 맞대어 검사 통과)
  pending: "#C9C1B8",
};

const SIZE = 168;
const STROKE = 24;
const RADIUS = (SIZE - STROKE - 10) / 2; // 마우스를 올리면 조각이 굵어져서 바깥 여유를 둔다
const CIRCLE = 2 * Math.PI * RADIUS;
const GAP = 3; // 조각 사이 바탕색 틈 (둘레 기준 px)

/** 이번 달 답장 상태: 정리한 답장의 수준별 비율. 가운데는 전체 수, 조각에 마우스를 올리면 그 상태의 수 */
export function LevelDonut({ levels }: { levels: MonthAnalysisTrends["levels"] }) {
  const [active, setActive] = useState<string | null>(null);
  const parts = levels.filter((level) => level.count > 0);
  const total = parts.reduce((sum, level) => sum + level.count, 0);
  if (!total) return null;
  const pct = (count: number) => Math.round((count / total) * 100);
  const gap = parts.length > 1 ? GAP : 0;
  let start = 0;
  const arcs = parts.map((part) => {
    const length = (part.count / total) * CIRCLE;
    const arc = { ...part, dash: Math.max(length - gap, 1), offset: start };
    start += length;
    return arc;
  });
  const focus = parts.find((part) => part.key === active) ?? null;

  return <div className="flex flex-col items-center gap-5 sm:flex-row lg:flex-col 2xl:flex-row">
    <div className="relative shrink-0" style={{ width: SIZE, height: SIZE }}>
      <svg width={SIZE} height={SIZE} viewBox={`0 0 ${SIZE} ${SIZE}`} className="-rotate-90" role="img"
        aria-label={`이번 달 답장 ${total}개: ${parts.map((part) => `${part.label} ${part.count}개`).join(", ")}`}>
        {arcs.map((arc) => <circle key={arc.key} cx={SIZE / 2} cy={SIZE / 2} r={RADIUS} fill="none"
          stroke={LEVEL_CHART[arc.key]} strokeWidth={active === arc.key ? STROKE + 6 : STROKE}
          strokeDasharray={`${arc.dash} ${CIRCLE - arc.dash}`} strokeDashoffset={-arc.offset}
          onMouseEnter={() => setActive(arc.key)} onMouseLeave={() => setActive(null)}
          className="transition-[stroke-width] duration-150">
          <title>{`${arc.label} ${arc.count}개 (${pct(arc.count)}%)`}</title>
        </circle>)}
      </svg>
      <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center text-center" aria-hidden="true">
        <span className="text-3xl font-extrabold tabular-nums text-[#3f3428]">{focus ? focus.count : total}<span className="text-base font-bold">개</span></span>
        <span className="mt-0.5 max-w-[6.5rem] text-[11px] font-semibold leading-4 text-stone-500">{focus ? focus.label : "이번 달 답장"}</span>
      </div>
    </div>
    <ul className="w-full min-w-0 max-w-[15rem] space-y-2">
      {levels.filter((level) => (level.key !== "pending" && level.key !== "resolved") || level.count > 0).map((level) => <li key={level.key}
        onMouseEnter={() => level.count && setActive(level.key)} onMouseLeave={() => setActive(null)}
        className={`flex items-center gap-2.5 rounded-lg px-2 py-1 text-sm ${active === level.key ? "bg-[#f6efe6]" : ""}`}>
        <span className="h-3 w-3 shrink-0 rounded-[3px]" style={{ background: LEVEL_CHART[level.key] }} />
        <span className="flex-1 text-[#4a3d30]">{level.label}</span>
        <span className="font-bold tabular-nums text-[#3f3428]">{level.count}개</span>
        <span className="w-9 text-right text-xs tabular-nums text-stone-500">{pct(level.count)}%</span>
      </li>)}
    </ul>
  </div>;
}
