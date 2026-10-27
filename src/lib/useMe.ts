"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { api, ApiError } from "./api";
import type { Me } from "./types";

/** 로그인한 사용자 정보. 로그인이 안 돼 있으면 첫 화면으로 보낸다. */
export function useMe() {
  const router = useRouter();
  const [me, setMe] = useState<Me | null>(null);
  const requestVersion = useRef(0);
  const cancelPendingRequests = useCallback(() => { requestVersion.current += 1; }, []);

  const reload = useCallback(async () => {
    const version = ++requestVersion.current;
    try {
      const data = await api<Me>("/api/me");
      if (version !== requestVersion.current) return null;
      setMe(data);
      return data;
    } catch (e) {
      if (version !== requestVersion.current) return null;
      if (e instanceof ApiError && e.status === 401) {
        setMe(null);
        const destination = window.location.pathname + window.location.search;
        router.replace(`/?next=${encodeURIComponent(destination)}`);
      }
      return null;
    }
  }, [router]);

  useEffect(() => {
    reload();
    const refresh = () => { if (document.visibilityState === "visible") void reload(); };
    window.addEventListener("focus", refresh);
    document.addEventListener("visibilitychange", refresh);
    return () => { cancelPendingRequests(); window.removeEventListener("focus", refresh); document.removeEventListener("visibilitychange", refresh); };
  }, [reload, cancelPendingRequests]);

  return { me, reload };
}

/** 가입 후 아직 안 끝난 첫 단계 */
export function nextOnboardingStep(me: Me): string | null {
  if (!me.consent_ok) return "/onboarding/consent";
  if (!me.parent) return "/onboarding/parent";
  if (me.voice.status === "none" || me.voice.status === "recording" || me.voice.status === "failed")
    return "/onboarding/voice";
  if (!me.photo) return "/onboarding/photo";
  return null;
}
