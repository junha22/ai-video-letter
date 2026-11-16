"use client";

import { useEffect, useRef, useState } from "react";
import { Camera, LoaderCircle, RotateCcw } from "lucide-react";
import { api, errorText } from "@/lib/api";
import type { RecipientPhoto } from "@/lib/conversations";
import { COVER_ACCEPT } from "./useAlbumCover";

type Props = {
  recipientId: number;
  name: string;
  photoUrl?: string | null;
  variant?: "photo" | "album-cover";
  onChange?: (photo: RecipientPhoto | null) => void;
  preview?: { upload: (file: File) => Promise<void>; reset: () => void };
};

export function RecipientPhotoEditor({ recipientId, name, photoUrl, onChange, preview, variant = "photo" }: Props) {
  const albumCover = variant === "album-cover";
  const label = albumCover ? `${name} 앨범 표지` : `${name} 사진`;
  const input = useRef<HTMLInputElement>(null);
  const lock = useRef(false);
  const mounted = useRef(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);

  const run = async (file?: File) => {
    if (lock.current) return;
    setError(""); setNotice("");
    if (file && !COVER_ACCEPT.split(",").includes(file.type)) { setError("JPG, PNG, WebP 이미지를 선택해 주세요."); return; }
    if (file && (!file.size || file.size > 15 * 1024 * 1024)) { setError("비어 있지 않은 15MB 이하 이미지를 선택해 주세요."); return; }
    lock.current = true; setBusy(true);
    try {
      if (preview) {
        if (file) await preview.upload(file); else preview.reset();
      } else if (file) {
        const form = new FormData(); form.append("file", file);
        const photo = await api<RecipientPhoto>(`/api/recipients/${recipientId}/photo`, { form });
        if (mounted.current) onChange?.(photo);
      } else {
        await api(`/api/recipients/${recipientId}/photo`, { method: "DELETE" });
        if (mounted.current) onChange?.(null);
      }
      if (mounted.current) setNotice(file ? `${name} 앨범의 표지를 저장했어요.` : "기본 일러스트 표지로 돌아왔어요.");
    } catch (e) {
      if (mounted.current) setError(errorText(e));
    } finally {
      lock.current = false;
      if (mounted.current) setBusy(false);
    }
  };

  return <div className="recipient-photo-editor">
    <input ref={input} type="file" className="sr-only" tabIndex={-1} accept={COVER_ACCEPT} aria-label={`${label} 선택`} disabled={busy} onChange={(event) => {
      const file = event.currentTarget.files?.[0]; event.currentTarget.value = "";
      if (file) void run(file);
    }} />
    <div className="recipient-photo-actions">
      <button type="button" aria-label={`${label} ${photoUrl ? "변경" : "등록"}`} disabled={busy} onClick={() => input.current?.click()}>
        {busy ? <LoaderCircle size={14} className="animate-spin" /> : <Camera size={14} />}{busy ? "저장 중…" : photoUrl ? (albumCover ? "표지 변경" : "사진 변경") : (albumCover ? "표지 등록" : "사진 등록")}
      </button>
      {photoUrl && <button type="button" aria-label={`${label} 삭제`} disabled={busy} onClick={() => { void run(); }}><RotateCcw size={13} />{albumCover ? "기본 표지로" : "일러스트로"}</button>}
    </div>
    <p className="recipient-photo-hint">{name} 앨범의 표지로만 사용해요. · 15MB 이하</p>
    {error && <p className="recipient-photo-error" role="alert">{error}</p>}
    <p className="recipient-photo-notice" role="status" aria-live="polite">{notice}</p>
  </div>;
}
