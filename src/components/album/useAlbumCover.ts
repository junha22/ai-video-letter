"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, errorText } from "@/lib/api";

type Cover = { url: string; width: number; height: number; updated_at: string };
export const COVER_ACCEPT = "image/jpeg,image/png,image/webp";
const ALLOWED = new Set(COVER_ACCEPT.split(","));

export function useAlbumCover({ preview = false, enabled = true }: { preview?: boolean; enabled?: boolean } = {}) {
  const [url, setUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(!preview);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState("");
  const lock = useRef(false);
  const objectUrl = useRef<string | null>(null);
  const mounted = useRef(true);

  const load = useCallback(async (signal?: AbortSignal) => {
    setLoading(true); setError(null);
    try {
      const cover = await api<Cover | null>("/api/album-cover", { signal });
      if (!signal?.aborted && mounted.current) setUrl(cover?.url ?? null);
    } catch (e) {
      if (!signal?.aborted && mounted.current) setError(errorText(e));
    } finally {
      if (!signal?.aborted && mounted.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      if (objectUrl.current) URL.revokeObjectURL(objectUrl.current);
    };
  }, []);
  useEffect(() => {
    if (preview || !enabled) return;
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [preview, enabled, load]);

  const select = async (file: File) => {
    if (lock.current) return;
    setError(null); setNotice("");
    if (!ALLOWED.has(file.type)) { setError("JPG, PNG, WebP 이미지를 선택해 주세요."); return; }
    if (file.size > 15 * 1024 * 1024) { setError("표지 이미지는 15MB 이하로 선택해 주세요."); return; }
    if (!file.size) { setError("비어 있는 파일이에요. 다른 이미지를 선택해 주세요."); return; }
    lock.current = true; setBusy(true);
    try {
      if (preview) {
        // Decode before replacing the last good cover, including files with a misleading MIME type.
        const image = await createImageBitmap(file);
        if (image.width * image.height > 40_000_000) { image.close(); throw new Error("이미지 해상도가 너무 커요. 4천만 화소 이하로 줄여 주세요."); }
        image.close();
        if (!mounted.current) return;
        const next = URL.createObjectURL(file);
        if (objectUrl.current) URL.revokeObjectURL(objectUrl.current);
        objectUrl.current = next;
        if (mounted.current) { setUrl(next); setNotice("이 탭의 표지를 바꿨어요. 프리뷰는 새로고침하면 초기화돼요."); }
      } else {
        const form = new FormData(); form.append("file", file);
        const cover = await api<Cover>("/api/album-cover", { form });
        if (mounted.current) { setUrl(cover.url); setNotice("앨범 표지를 저장했어요."); }
      }
    } catch (e) {
      if (mounted.current) setError(preview && !(e instanceof Error && e.message.includes("해상도")) ? "이미지를 읽지 못했어요. 정상적인 JPG, PNG, WebP 파일을 선택해 주세요." : errorText(e));
    } finally {
      lock.current = false;
      if (mounted.current) setBusy(false);
    }
  };

  const reset = async () => {
    if (lock.current) return;
    lock.current = true; setBusy(true); setError(null); setNotice("");
    try {
      if (!preview) await api("/api/album-cover", { method: "DELETE" });
      if (objectUrl.current) { URL.revokeObjectURL(objectUrl.current); objectUrl.current = null; }
      if (mounted.current) { setUrl(null); setNotice(preview ? "이 탭에서 기본 표지로 돌아왔어요." : "기본 표지로 돌아왔어요."); }
    } catch (e) {
      if (mounted.current) setError(errorText(e));
    } finally {
      lock.current = false;
      if (mounted.current) setBusy(false);
    }
  };

  return { url, loading, busy, error, notice, select, reset, retry: () => { if (preview) setError(null); else void load(); } };
}

export type AlbumCoverState = ReturnType<typeof useAlbumCover>;
