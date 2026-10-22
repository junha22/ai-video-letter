"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Camera, CircleAlert, CircleCheck } from "lucide-react";
import { api, errorText } from "@/lib/api";
import type { PhotoInfo } from "@/lib/types";
import { AppShell } from "@/components/AppShell";
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
        <>
          <Card>
            <p className="mb-2 font-bold text-stone-900">이런 사진이 좋아요</p>
            <ul className="list-disc space-y-1 pl-5 text-[15px] text-stone-700">
              <li>정면을 바라보고 혼자 나온 사진</li>
              <li>얼굴이 화면의 3분의 1 이상으로 크게 나온 사진</li>
              <li>밝은 곳에서 찍은 선명한 사진 (모자·선글라스·마스크 없이)</li>
            </ul>
          </Card>

          <div className="mt-5">
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
            ) : null}
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
        </>
      )}
    </AppShell>
  );
}
