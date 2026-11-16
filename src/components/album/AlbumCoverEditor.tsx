"use client";

import { useRef } from "react";
import { Camera, LoaderCircle, RotateCcw } from "lucide-react";
import { COVER_ACCEPT, type AlbumCoverState } from "./useAlbumCover";

export function AlbumCoverEditor({ cover }: { cover: AlbumCoverState }) {
  const input = useRef<HTMLInputElement>(null);
  const disabled = cover.busy || cover.loading;
  return <div className="album-cover-editor">
    <input ref={input} className="sr-only" tabIndex={-1} type="file" accept={COVER_ACCEPT} aria-label="앨범 표지 이미지 선택" disabled={disabled} onChange={(event) => {
      const file = event.currentTarget.files?.[0];
      event.currentTarget.value = "";
      if (file) void cover.select(file);
    }} />
    <div className="album-cover-editor-buttons">
      <button type="button" disabled={disabled} onClick={() => input.current?.click()}>
        {disabled ? <LoaderCircle size={15} className="animate-spin" /> : <Camera size={15} />}
        {cover.busy ? "표지 저장 중…" : cover.loading ? "표지 불러오는 중…" : "표지 바꾸기"}
      </button>
      {cover.url && <button type="button" disabled={disabled} onClick={() => { void cover.reset(); }}><RotateCcw size={14} />기본 표지로</button>}
    </div>
    <p className="album-cover-file-hint">JPG · PNG · WebP / 15MB 이하 · 영상용 얼굴 사진과 별도로 저장해요.</p>
    {cover.error && <p role="alert" className="album-cover-error">{cover.error}{!cover.url && <button type="button" disabled={disabled} onClick={cover.retry}>다시 불러오기</button>}</p>}
    <p role="status" aria-live="polite" className="album-cover-notice">{cover.notice}</p>
  </div>;
}
