"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { Pause, Play, RotateCcw } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { formatDate, nameSubject } from "@/lib/format";
import type { WatchInfo } from "@/lib/types";

/** 부모님이 카톡·문자 링크를 눌러 들어오는 화면. 로그인 없이, 큰 버튼 하나로 본다. */
export default function WatchPage() {
  const { token } = useParams<{ token: string }>();
  const video = useRef<HTMLVideoElement>(null);
  const reported = useRef(false);
  const [info, setInfo] = useState<WatchInfo | null>(null);
  const [error, setError] = useState<{ status: number; text: string } | null>(null);
  const [started, setStarted] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [ended, setEnded] = useState(false);
  const [time, setTime] = useState(0);

  useEffect(() => {
    api<WatchInfo>(`/api/watch/${token}`)
      .then(setInfo)
      .catch((e) => setError({ status: e instanceof ApiError ? e.status : 0, text: e.message }));
  }, [token]);

  const play = async () => {
    const v = video.current;
    if (!v) return;
    if (ended) v.currentTime = 0;
    try {
      // 소리가 나는 자동재생은 브라우저가 막기 때문에 버튼을 누를 때 재생한다
      await v.play();
    } catch {
      return;
    }
    setStarted(true);
    setEnded(false);
    if (!reported.current) {
      reported.current = true;
      api(`/api/watch/${token}/viewed`, { method: "POST" }).catch(() => {});
    }
  };

  const restart = () => {
    if (!video.current) return;
    video.current.currentTime = 0;
    play();
  };

  if (error) {
    return (
      <Shell>
        <div className="py-20 text-center">
          <p className="text-3xl font-black text-stone-900">{error.status === 410 ? "볼 수 없는 영상이에요" : "영상을 찾을 수 없어요"}</p>
          <p className="mt-4 text-xl leading-relaxed text-stone-700">
            {error.status === 410 ? "링크 기간이 지났거나 삭제된 영상이에요." : "링크 주소가 맞는지 확인해 주세요."}
            <br />
            보낸 분께 다시 보내 달라고 말씀해 주세요.
          </p>
        </div>
      </Shell>
    );
  }

  if (!info) {
    return (
      <Shell>
        <p className="py-24 text-center text-2xl font-bold text-stone-600">불러오는 중…</p>
      </Shell>
    );
  }

  const caption = info.captions.find((c) => time >= c.start && time < c.end)?.text ?? "";

  return (
    <Shell>
      <h1 className="text-[30px] font-black leading-tight text-stone-900">
        {nameSubject(info.child_name)}
        <br />
        영상 편지를 보냈어요
      </h1>
      <p className="mt-2 text-lg text-stone-600">{formatDate(info.created_at)}</p>

      <div className="relative mt-5 aspect-[4/5] w-full overflow-hidden rounded-[28px] bg-black shadow-xl">
        <video
          ref={video}
          src={info.video_url}
          poster={info.poster_url}
          playsInline
          preload="auto"
          controls={started}
          onPlay={() => setPlaying(true)}
          onPause={() => setPlaying(false)}
          onEnded={() => {
            setPlaying(false);
            setEnded(true);
          }}
          onTimeUpdate={(e) => setTime(e.currentTarget.currentTime)}
          className="h-full w-full object-cover"
        />
        {(!started || ended) && (
          <button
            onClick={play}
            className="absolute inset-0 flex flex-col items-center justify-center gap-4 bg-black/35"
            aria-label="영상 보기"
          >
            <span className="flex h-28 w-28 items-center justify-center rounded-full bg-amber-400 shadow-2xl">
              {ended ? (
                <RotateCcw className="h-14 w-14 text-stone-900" strokeWidth={2.5} />
              ) : (
                <Play className="ml-2 h-14 w-14 fill-stone-900 text-stone-900" />
              )}
            </span>
            <span className="rounded-full bg-black/70 px-6 py-2.5 text-2xl font-black text-white">
              {ended ? "다시 보기" : "눌러서 보기"}
            </span>
          </button>
        )}
      </div>

      <p className="mt-5 min-h-[5.5rem] text-center text-[28px] font-bold leading-snug text-stone-900">
        {started ? caption : "소리를 켜고 보세요"}
      </p>

      {started && !ended && (
        <div className="mt-2 grid grid-cols-2 gap-3">
          <button
            onClick={() => (playing ? video.current?.pause() : play())}
            className="flex h-16 items-center justify-center gap-2 rounded-2xl bg-stone-900 text-xl font-bold text-white"
          >
            {playing ? <Pause className="h-7 w-7 fill-white" /> : <Play className="h-7 w-7 fill-white" />}
            {playing ? "멈춤" : "계속 보기"}
          </button>
          <button
            onClick={restart}
            className="flex h-16 items-center justify-center gap-2 rounded-2xl border-2 border-stone-300 bg-white text-xl font-bold text-stone-900"
          >
            <RotateCcw className="h-7 w-7" /> 처음부터
          </button>
        </div>
      )}

      <p className="mt-8 rounded-2xl bg-white/70 px-4 py-3 text-base leading-relaxed text-stone-600">
        이 영상은 {nameSubject(info.child_name)} 직접 쓴 말을 AI가 {info.child_name}의 목소리와 얼굴로 만든 영상이에요.
      </p>

      {info.others.length > 0 && (
        <div className="mt-10">
          <h2 className="mb-3 text-2xl font-black text-stone-900">지난 영상 편지</h2>
          <ul className="space-y-3">
            {info.others.map((o) => (
              <li key={o.token}>
                <Link href={`/w/${o.token}`} className="flex items-center gap-4 rounded-2xl bg-white p-4 shadow-sm">
                  <span className="flex h-14 w-14 shrink-0 items-center justify-center rounded-full bg-amber-400">
                    <Play className="ml-1 h-7 w-7 fill-stone-900 text-stone-900" />
                  </span>
                  <span className="min-w-0">
                    <span className="block text-lg font-bold text-stone-900">{formatDate(o.created_at)}</span>
                    <span className="block truncate text-base text-stone-600">{o.preview}</span>
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </div>
      )}
    </Shell>
  );
}

function Shell({ children }: { children: React.ReactNode }) {
  return <div className="mx-auto min-h-screen max-w-md bg-[#FFF8EF] px-5 pb-16 pt-8">{children}</div>;
}
