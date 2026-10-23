"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Camera, CircleAlert, CircleCheck } from "lucide-react";
import { api, errorText } from "@/lib/api";
import type { PhotoInfo } from "@/lib/types";
import { AppShell } from "@/components/AppShell";
import { PhotoGuide, PhotoPlaceholder } from "@/components/StudioPanels";
import { Button, Card, LinkButton, Notice, Spinner, StepHeader } from "@/components/ui";

type UploadResult = { ok: boolean; problems: string[]; photo: PhotoInfo | null };

export default function PhotoPage() {
  const router = useRouter();
  const fileRef = useRef<HTMLInputElement>(null);
  const [photo, setPhoto] = useState<PhotoInfo | null | undefined>(undefined);
  const [preview, setPreview] = useState<string | null>(null);
  const [problems, setProblems] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api<PhotoInfo | null>("/api/photo")
      .then(setPhoto)
      .catch(() => router.replace("/"));
  }, [router]);

  const onFile = async (file: File | undefined) => {
    if (!file) return;
    setPreview(URL.createObjectURL(file));
    setProblems([]);
    setBusy(true);
    try {
      const form = new FormData();
      form.append("file", file);
      const r = await api<UploadResult>("/api/photo", { form });
      if (r.ok) {
        setPhoto(r.photo);
        setPreview(null);
      } else {
        setProblems(r.problems);
      }
    } catch (e) {
      setProblems([errorText(e)]);
    }
    setBusy(false);
    if (fileRef.current) fileRef.current.value = "";
  };

  return (
    <AppShell back="/home">
      <StepHeader step={4} total={4} title="얼굴 사진을 올려 주세요" desc="이 사진으로 영상 속 내 모습을 만들어요." />
      {photo === undefined ? (
        <Spinner />
      ) : (
        <div className="grid items-start gap-6 lg:grid-cols-[0.85fr_1.15fr]">
          <PhotoGuide />
          <Card className="min-w-0 !rounded-[28px] p-6 sm:p-8">
          <div className="mb-6 flex items-center justify-between gap-3"><div><p className="text-[10px] font-bold tracking-[0.16em] text-[#a77c65]">MY PORTRAIT</p><h2 className="mt-2 text-xl font-bold text-[#293d31]">마음에 담을 나의 얼굴</h2></div><span className="rounded-full bg-[#f0f4ea] px-3 py-1.5 text-[10px] text-[#75896d]">사진 1장</span></div>
          <div>
            {preview || photo ? (
              <div className="relative mx-auto aspect-[4/5] w-full max-w-xs overflow-hidden rounded-3xl bg-stone-200">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={preview ?? photo!.url} alt="올린 사진" className="h-full w-full object-cover" />
                {busy && (
                  <div className="absolute inset-0 flex items-center justify-center bg-black/40 text-white">
                    <Spinner label="사진을 확인하고 있어요" />
                  </div>
                )}
              </div>
            ) : <PhotoPlaceholder />}
          </div>

          {problems.length > 0 && (
            <div className="mt-4">
              <Notice tone="error">
                <span className="mb-1 flex items-center gap-2 font-bold">
                  <CircleAlert className="h-5 w-5" /> 다른 사진을 올려 주세요
                </span>
                {problems.map((p) => (
                  <span key={p} className="block">
                    {p}
                  </span>
                ))}
              </Notice>
            </div>
          )}
          {photo && !preview && (
            <div className="mt-4">
              <Notice tone="success">
                <span className="flex items-center gap-2 font-bold">
                  <CircleCheck className="h-5 w-5" /> 사진이 등록됐어요
                </span>
              </Notice>
            </div>
          )}

          <input
            ref={fileRef}
            type="file"
            accept="image/*"
            className="hidden"
            onChange={(e) => onFile(e.target.files?.[0])}
          />
          <Button
            variant={photo ? "secondary" : "primary"}
            onClick={() => fileRef.current?.click()}
            loading={busy}
            className="mt-6 w-full"
          >
            <Camera className="h-5 w-5" /> {photo ? "다른 사진으로 바꾸기" : "사진 고르기"}
          </Button>
          {photo && (
            <LinkButton href="/home" className="mt-3 w-full">
              완료
            </LinkButton>
          )}
          <p className="mt-4 text-center text-[11px] leading-6 text-[#909b86]">사진을 고르면 얼굴과 화질을 확인해 드려요.</p>
          </Card>
        </div>
      )}
    </AppShell>
  );
}
