import Link from "next/link";
import { LoaderCircle } from "lucide-react";
import type { ComponentProps, ReactNode } from "react";

type Variant = "primary" | "secondary" | "ghost" | "danger";

const VARIANTS: Record<Variant, string> = {
  primary: "bg-ongi-800 text-white hover:bg-ongi-900 disabled:bg-stone-300 disabled:text-stone-500",
  secondary: "bg-white text-stone-800 border border-stone-300 hover:bg-stone-50 disabled:text-stone-400",
  ghost: "text-stone-700 hover:bg-stone-100 disabled:text-stone-400",
  danger: "bg-white text-red-700 border border-red-300 hover:bg-red-50",
};

const BASE =
  "inline-flex items-center justify-center gap-2 rounded-2xl px-5 py-3.5 text-base font-bold transition-colors disabled:cursor-not-allowed";

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
  return <section className={`rounded-3xl border border-stone-200 bg-white p-5 ${className}`}>{children}</section>;
}

export function Progress({ value, className = "" }: { value: number; className?: string }) {
  return (
    <div className={`h-3 w-full overflow-hidden rounded-full bg-stone-200 ${className}`}>
      <div
        className="h-full rounded-full bg-ongi-700 transition-[width] duration-500"
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
    <div className="mb-6">
      <div className="mb-3 flex gap-1.5">
        {Array.from({ length: total }, (_, i) => (
          <div key={i} className={`h-1.5 flex-1 rounded-full ${i < step ? "bg-ongi-700" : "bg-stone-200"}`} />
        ))}
      </div>
      <p className="text-sm font-bold text-ongi-700">
        {step} / {total}단계
      </p>
      <h1 className="mt-1 text-2xl font-extrabold text-stone-900">{title}</h1>
      {desc && <p className="mt-2 text-[15px] leading-relaxed text-stone-600">{desc}</p>}
    </div>
  );
}
