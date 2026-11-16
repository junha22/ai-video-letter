"use client";
import Image from "next/image";
import { useEffect, useState } from "react";
import { Heart, Pause, Play, RotateCcw } from "lucide-react";
import { EMPTY_LOGIN_VALUES, LoginOptions, type LoginMode } from "@/components/LoginScreen";
export const TOPICS = {
  안부: "엄마, 오늘 하루는 어땠어요? 특별한 일은 없지만 문득 엄마 생각이 났어요. 밥 잘 챙겨 드시고, 오늘도 편안한 저녁 보내요. 사랑해요!",
  건강: "아침저녁으로 많이 쌀쌀해졌죠? 외출할 때 따뜻하게 입고, 식사도 꼭 챙겨 드세요. 이번 주말에 좋아하시는 과일 사서 찾아뵐게요!",
  감사: "늘 내 편이 되어 주셔서 고마워요. 표현은 서툴러도 항상 감사하고 있어요. 오늘은 꼭 이 말을 전하고 싶었어요. 사랑해요.",
};
export type Topic = keyof typeof TOPICS;
export function PreviewRibbon({ label }: { label: string }) {
 return <div className="concept-ribbon"><span>DESIGN PREVIEW · {label}</span><span>샘플 데이터 · 실제 녹음·생성·발송 없음</span></div>;
}
export function Brand({ onClick, subtitle }: { onClick: () => void; subtitle?: string }) {
 return <button className="concept-brand" onClick={onClick} aria-label="첫 화면으로"><span><Heart size={20} fill="currentColor" /></span><strong>온기</strong>{subtitle && <small>{subtitle}</small>}</button>;
}
export function Photo({ kind = "family", className = "" }: { kind?: "family" | "son" | "daughter"; className?: string }) {
 const src = kind === "family" ? "family-together" : `${kind}-character`;
 return <div className={`concept-photo ${className}`}><Image src={`/images/${src}.webp`} alt={kind === "family" ? "미소 짓는 우리 가족 일러스트" : kind === "son" ? "지민의 아들 캐릭터" : "지민의 딸 캐릭터"} fill sizes="(min-width: 1000px) 600px, 90vw" priority /></div>;
}
export function useSamplePlayback(message: string) {
 const [playing, setPlaying] = useState(false);
 const [progress, setProgress] = useState(0);
 useEffect(() => { setPlaying(false); setProgress(0); }, [message]);
 useEffect(() => {
  if (!playing) return;
  const timer = window.setInterval(() => setProgress(p => Math.min(100, p + 1)), 220);
  return () => window.clearInterval(timer);
 }, [playing]);
 useEffect(() => { if (progress === 100) setPlaying(false); }, [progress]);
 return { playing, progress, seek: setProgress, toggle: () => { if (progress === 100) setProgress(0); setPlaying(p => !p); } };
}
export function StoryPlayer({ message, character = "son", playback, caption = true }: { message: string; character?: "son" | "daughter"; playback: ReturnType<typeof useSamplePlayback>; caption?: boolean }) {
 const characters = Array.from(message);
 const chunks = characters.length ? Array.from({ length: Math.ceil(characters.length / 34) }, (_, i) => characters.slice(i * 34, (i + 1) * 34).join("")) : ["오늘의 마음을 적어 주세요."];
 const subtitle = chunks[Math.min(chunks.length - 1, Math.floor(playback.progress / 100 * chunks.length))];
 return <div className="story-player">
   <div className="story-stage"><Photo kind={character} /><span className="story-label">정적 이미지 + 자막 · 샘플</span>{caption && <p className="story-subtitle">{subtitle}</p>}<button className="story-play" aria-label={playback.playing ? "샘플 일시정지" : "샘플 재생"} onClick={playback.toggle}>{playback.playing ? <Pause size={25} fill="currentColor" /> : <Play size={25} fill="currentColor" />}</button></div>
   <div className="story-controls"><button aria-label="처음부터 보기" onClick={() => playback.seek(0)}><RotateCcw size={15} /></button><span>{String(Math.floor(playback.progress * .22)).padStart(2, "0")} / 22초</span><input aria-label="샘플 재생 위치" type="range" min="0" max="100" value={playback.progress} onChange={e => playback.seek(Number(e.target.value))} /><span>샘플</span></div>
 </div>;
}
export function PreviewLogin() {
 const [mode, setMode] = useState<LoginMode>("login");
 const [values, setValues] = useState(EMPTY_LOGIN_VALUES);
 const [notice, setNotice] = useState("");
 const sample = () => setNotice("샘플 로그인입니다. 계정 정보는 저장하거나 전송하지 않았어요.");
 return <div className="concept-login"><span className="concept-eyebrow">WELCOME TO OUR FAMILY</span><h1>다시 만나 반가워요.</h1><p>소중한 가족과의 이야기를 이어가요.</p><LoginOptions config={{password_login: true, dev_login: false, password_min_length: 4, password_max_length: null}} mode={mode} values={values} busy={false} error={null} onModeChange={setMode} onValueChange={(key,value) => setValues(v => ({...v,[key]: value}))} onSubmit={event => {event.preventDefault();sample();}} onDevLogin={event => {event.preventDefault();sample();}} onRetry={sample} /><p role="status" aria-live="polite">{notice}</p></div>;
}
