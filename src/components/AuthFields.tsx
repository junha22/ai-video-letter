"use client";

import { useState, type ComponentProps } from "react";
import { Eye, EyeOff } from "lucide-react";

export const AUTH_INPUT_CLASS = "min-h-12 w-full min-w-0 rounded-xl border border-[#d6dfd2] bg-white px-3 py-3 text-base text-[#2e342f] outline-none placeholder:text-[#929b90] focus:border-[#315d4b] focus:ring-2 focus:ring-[#dce8d8] disabled:cursor-not-allowed disabled:bg-stone-100";

type FieldProps = ComponentProps<"input"> & { id: string; label: string; hint?: string };

export function AuthField({ id, label, hint, className = "", ...props }: FieldProps) {
  return (
    <div>
      <label htmlFor={id} className="mb-2 block text-sm font-semibold text-[#445846]">{label}</label>
      <input id={id} aria-describedby={hint ? `${id}-hint` : undefined} className={`${AUTH_INPUT_CLASS} ${className}`} {...props} />
      {hint && <p id={`${id}-hint`} className="mt-2 text-xs leading-5 text-[#737d74]">{hint}</p>}
    </div>
  );
}

export function PasswordField({ id, label, hint, className = "", ...props }: Omit<FieldProps, "type">) {
  const [visible, setVisible] = useState(false);
  return (
    <div>
      <label htmlFor={id} className="mb-2 block text-sm font-semibold text-[#445846]">{label}</label>
      <div className="relative">
        <input id={id} type={visible ? "text" : "password"} aria-describedby={hint ? `${id}-hint` : undefined} className={`${AUTH_INPUT_CLASS} pr-14 ${className}`} {...props} />
        <button type="button" onClick={() => setVisible((value) => !value)} disabled={props.disabled} aria-label={`${label} ${visible ? "숨기기" : "보기"}`} aria-pressed={visible} className="absolute inset-y-0 right-0 flex min-w-12 items-center justify-center rounded-xl text-[#647568] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#315d4b] disabled:opacity-50">
          {visible ? <EyeOff size={20} aria-hidden="true" /> : <Eye size={20} aria-hidden="true" />}
        </button>
      </div>
      {hint && <p id={`${id}-hint`} className="mt-2 text-xs leading-5 text-[#737d74]">{hint}</p>}
    </div>
  );
}
