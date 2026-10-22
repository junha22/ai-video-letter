"use client";

import { useState } from "react";
import { Check, Copy, MessageCircle, Share2, Smartphone } from "lucide-react";
import { api } from "@/lib/api";
import { formatDate, nameSubject } from "@/lib/format";
import type { Message } from "@/lib/types";
import { Button, Notice } from "./ui";

const KAKAO_JS_KEY = process.env.NEXT_PUBLIC_KAKAO_JS_KEY;
const KAKAO_SDK = "https://t1.kakaocdn.net/kakao_js_sdk/2.7.2/kakao.min.js";

type KakaoSDK = {
  isInitialized(): boolean;
  init(key: string): void;
  Share: { sendDefault(options: object): void };
};

function loadKakao(): Promise<KakaoSDK> {
  const w = window as unknown as { Kakao?: KakaoSDK };
  if (w.Kakao) return Promise.resolve(w.Kakao);
  return new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = KAKAO_SDK;
    script.onload = () => (w.Kakao ? resolve(w.Kakao) : reject(new Error("카카오 SDK를 불러오지 못했어요.")));
    script.onerror = () => reject(new Error("카카오 SDK를 불러오지 못했어요."));
    document.head.appendChild(script);
  });
}

/** 승인한 영상의 시청 링크를 부모님께 보내는 버튼들 */
export function SharePanel({
  message,
  childName,
  phone,
  onSent,
}: {
  message: Message;
  childName: string;
  phone?: string;
  onSent: (m: Message) => void;
}) {
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const share = message.share!;
  const title = `${nameSubject(childName)} 영상 편지를 보냈어요`;
  const text = `${title}\n아래 링크를 누르고 재생 버튼을 눌러 보세요.\n${share.url}`;
  const local = /localhost|127\.0\.0\.1/.test(share.url);
  const canNativeShare = typeof navigator !== "undefined" && "share" in navigator;

  const markSent = async (channel: string) => {
    onSent(await api<Message>(`/api/messages/${message.id}/sent`, { json: { channel } }));
  };

  const kakao = async () => {
    setError(null);
    try {
      const Kakao = await loadKakao();
      if (!Kakao.isInitialized()) Kakao.init(KAKAO_JS_KEY!);
      Kakao.Share.sendDefault({
        objectType: "text",
        text: `${title}\n눌러서 바로 보세요.`,
        link: { mobileWebUrl: share.url, webUrl: share.url },
        buttonTitle: "영상 보기",
      });
      await markSent("kakao");
    } catch (e) {
      setError(e instanceof Error ? e.message : "카카오톡 공유에 실패했어요.");
    }
  };

  const nativeShare = async () => {
    try {
      await navigator.share({ title, text: `${title}\n아래 링크를 누르고 재생 버튼을 눌러 보세요.`, url: share.url });
      await markSent("share");
    } catch {
      // 공유 창을 닫은 경우
    }
  };

  const copy = async () => {
    await navigator.clipboard.writeText(text);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 2000);
    await markSent("copy");
  };

  return (
    <div className="space-y-3">
      {local && (
        <Notice>
          지금 링크는 이 컴퓨터에서만 열려요. 부모님 휴대폰에서 열리게 하려면 backend/.env의 PUBLIC_BASE_URL을 배포
          주소나 터널(ngrok 등) 주소로 바꿔 주세요.
        </Notice>
      )}
      {error && <Notice tone="error">{error}</Notice>}

      {KAKAO_JS_KEY ? (
        <button
          onClick={kakao}
          className="flex w-full items-center justify-center gap-2 rounded-2xl bg-[#FEE500] py-4 text-[17px] font-bold text-[#191919]"
        >
          <MessageCircle className="h-5 w-5" /> 카카오톡으로 보내기
        </button>
      ) : (
        canNativeShare && (
          <Button onClick={nativeShare} className="w-full">
            <Share2 className="h-5 w-5" /> 카카오톡 등으로 공유하기
          </Button>
        )
      )}
      {phone && (
        <a
          href={`sms:${phone.replace(/-/g, "")}?&body=${encodeURIComponent(text)}`}
          onClick={() => markSent("sms")}
          className="flex w-full items-center justify-center gap-2 rounded-2xl border border-stone-300 bg-white py-3.5 text-base font-bold text-stone-800"
        >
          <Smartphone className="h-5 w-5" /> 문자로 보내기
        </a>
      )}
      <Button variant="secondary" onClick={copy} className="w-full">
        {copied ? <Check className="h-5 w-5 text-emerald-600" /> : <Copy className="h-5 w-5" />}
        {copied ? "복사했어요" : "링크 복사하기"}
      </Button>

      <p className="break-all rounded-xl bg-stone-100 px-3 py-2 text-xs text-stone-500">{share.url}</p>
      <p className="text-center text-xs text-stone-400">{formatDate(share.expires_at)}까지 볼 수 있어요</p>
    </div>
  );
}
