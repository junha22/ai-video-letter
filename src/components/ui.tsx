import Link from "next/link";
import { LoaderCircle } from "lucide-react";
import type { ComponentProps, ReactNode } from "react";

type Variant = "primary" | "secondary" | "ghost" | "danger";

const VARIANTS: Record<Variant, string> = {
  primary: "bg-[#315d4b] text-white shadow-[0_4px_12px_rgba(49,93,75,0.12)] hover:bg-[#234b39] disabled:bg-stone-300 disabled:text-stone-500 disabled:shadow-none",
  secondary: "bg-white text-stone-800 border border-stone-300 hover:bg-stone-50 disabled:text-stone-400",
  ghost: "text-stone-700 hover:bg-stone-100 disabled:text-stone-400",
  danger: "bg-white text-red-700 border border-red-300 hover:bg-red-50",
};

const BASE =
  "inline-flex min-h-12 items-center justify-center gap-2 rounded-2xl px-5 py-3.5 text-[15px] font-semibold transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-[#79967c] disabled:cursor-not-allowed";

export function Button({
  variant = "primary",
  loading,
  className = "",
  children,
  disabled,
  ...props
}: ComponentProps<"button"> & { variant?: Variant; loading?: boolean }) {
  return (
    <button className={`${BASE} ${VARIANTS[variant]} ${className}`} disabled={disabled || loading} {...props}>
      {loading && <LoaderCircle className="h-5 w-5 animate-spin" />}
      {children}
    </button>
  );
}

export function LinkButton({
  variant = "primary",
  className = "",
  ...props
}: ComponentProps<typeof Link> & { variant?: Variant }) {
  return <Link className={`${BASE} ${VARIANTS[variant]} ${className}`} {...props} />;
}

// 파일 내려받기처럼 Next 라우팅을 거치지 않는 링크
export function AnchorButton({ variant = "primary", className = "", ...props }: ComponentProps<"a"> & { variant?: Variant }) {
  return <a className={`${BASE} ${VARIANTS[variant]} ${className}`} {...props} />;
}

export function Card({ className = "", children }: { className?: string; children: ReactNode }) {
  return <section className={`rounded-3xl border border-stone-200 bg-white p-5 shadow-[0_5px_18px_rgba(32,42,32,0.04)] ${className}`}>{children}</section>;
}

export function Progress({ value, className = "" }: { value: number; className?: string }) {
  return (
    <div className={`h-3 w-full overflow-hidden rounded-full bg-stone-200 ${className}`}>
      <div
        className="h-full rounded-full bg-[#315d4b] transition-[width] duration-500"
        style={{ width: `${Math.min(100, Math.max(0, value * 100))}%` }}
      />
    </div>
  );
}

export function Spinner({ label }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-2 py-10 text-stone-500">
      <LoaderCircle className="h-5 w-5 animate-spin" />
      {label && <span>{label}</span>}
    </div>
  );
}

export function Notice({ tone = "info", children }: { tone?: "info" | "error" | "success"; children: ReactNode }) {
  const styles = {
    info: "bg-amber-50 border-amber-200 text-amber-950",
    error: "bg-red-50 border-red-200 text-red-800",
    success: "bg-emerald-50 border-emerald-200 text-emerald-900",
  }[tone];
  return <div className={`rounded-2xl border px-4 py-3 text-sm leading-relaxed ${styles}`}>{children}</div>;
}

export function StepHeader({ step, total, title, desc }: { step: number; total: number; title: string; desc?: ReactNode }) {
  return (
    <div className="mb-8">
      <ol aria-label="편지 준비 단계" className="mb-7 flex max-w-xl items-center gap-2 sm:gap-4">
        {Array.from({ length: total }, (_, i) => (
          <li key={i} aria-current={i + 1 === step ? "step" : undefined} className={`flex min-w-0 flex-1 items-center gap-2 text-[10px] sm:text-xs ${i + 1 === step ? "font-semibold text-[#315d4b]" : "text-[#9ba592]"}`}><span className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[10px] ${i + 1 === step ? "bg-[#315d4b] text-white" : "border border-[#e0e6d8] bg-[#f0f3e9]"}`}>{String(i + 1).padStart(2, "0")}</span><span>{total === 4 ? ["동의", "받는 분", "목소리", "사진"][i] : `${i + 1}단계`}</span></li>
        ))}
      </ol>
      <p className="text-[10px] font-bold tracking-[0.16em] text-[#a77c65]">
        STEP {String(step).padStart(2, "0")} / {String(total).padStart(2, "0")}
      </p>
      <h1 className="mt-3 text-[27px] font-bold tracking-tighter text-[#2b3d30] sm:text-[34px]">{title}</h1>
      {desc && <p className="mt-3 max-w-2xl text-sm leading-7 text-[#7c8775]">{desc}</p>}
    </div>
  );
}
