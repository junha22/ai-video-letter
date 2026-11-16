"use client";

import { useState, type ComponentProps } from "react";
import { Eye, EyeOff } from "lucide-react";

export const AUTH_INPUT_CLASS = "min-h-12 w-full min-w-0 rounded-xl border border-[#ead9cd] bg-white px-3 py-3 text-base text-[#493035] outline-none placeholder:text-[#81645d] focus:border-[#c8493c] focus:ring-2 focus:ring-[#ead9cd] disabled:cursor-not-allowed disabled:bg-stone-100";

type FieldProps = ComponentProps<"input"> & { id: string; label: string; hint?: string };

export function AuthField({ id, label, hint, className = "", ...props }: FieldProps) {
  return (
    <div>
      <label htmlFor={id} className="mb-2 block text-sm font-semibold text-[#81645d]">{label}</label>
      <input id={id} aria-describedby={hint ? `${id}-hint` : undefined} className={`${AUTH_INPUT_CLASS} ${className}`} {...props} />
      {hint && <p id={`${id}-hint`} className="mt-2 text-xs leading-5 text-[#81645d]">{hint}</p>}
    </div>
  );
}

export function PasswordField({ id, label, hint, className = "", ...props }: Omit<FieldProps, "type">) {
  const [visible, setVisible] = useState(false);
  return (
    <div>
      <label htmlFor={id} className="mb-2 block text-sm font-semibold text-[#81645d]">{label}</label>
      <div className="relative">
        <input id={id} type={visible ? "text" : "password"} aria-describedby={hint ? `${id}-hint` : undefined} className={`${AUTH_INPUT_CLASS} pr-14 ${className}`} {...props} />
        <button type="button" onClick={() => setVisible((value) => !value)} disabled={props.disabled} aria-label={`${label} ${visible ? "숨기기" : "보기"}`} aria-pressed={visible} className="absolute inset-y-0 right-0 flex min-w-12 items-center justify-center rounded-xl text-[#81645d] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#c8493c] disabled:opacity-50">
          {visible ? <EyeOff size={20} aria-hidden="true" /> : <Eye size={20} aria-hidden="true" />}
        </button>
      </div>
      {hint && <p id={`${id}-hint`} className="mt-2 text-xs leading-5 text-[#81645d]">{hint}</p>}
    </div>
  );
}
