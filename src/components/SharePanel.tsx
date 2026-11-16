"use client";

import { useEffect, useState } from "react";
import QRCode from "qrcode";
import { Check, Copy, MessageCircle, QrCode, Share2, Smartphone } from "lucide-react";
import { api, errorText } from "@/lib/api";
import type { Recipient } from "@/lib/conversations";
import { formatDate, nameSubject } from "@/lib/format";
import type { Message } from "@/lib/types";
import { Button, Notice } from "./ui";

const KAKAO_SDK = "https://t1.kakaocdn.net/kakao_js_sdk/2.7.2/kakao.min.js";

// 카카오 JavaScript 키는 실행할 때 웹 서버(/web-config)에서 받는다. 빈 값이면 카카오톡 버튼 대신 휴대폰 공유 창을 보인다
let kakaoKeyRequest: Promise<string> | null = null;
function kakaoJsKey(): Promise<string> {
  kakaoKeyRequest ??= fetch("/web-config", { cache: "no-store" })
    .then((res) => (res.ok ? res.json() : {}))
    .then((config: { kakao_js_key?: string }) => config.kakao_js_key || "")
    .catch(() => {
      kakaoKeyRequest = null; // 다음에 다시 시도한다
      return "";
    });
  return kakaoKeyRequest;
}

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

const PHONE = /^01\d{8,9}$/;
const digitsOf = (value: string) => value.replace(/\D/g, "");
const formatPhone = (digits: string) => `${digits.slice(0, 3)}-${digits.slice(3, -4)}-${digits.slice(-4)}`;

/** 휴대폰에서 연 화면인지 (iPadOS는 Mac으로 보이므로 터치 지점 수로 가린다) */
function isMobileDevice(): boolean {
  return /Android|iPhone|iPad|iPod/i.test(navigator.userAgent)
    || (/Macintosh/.test(navigator.userAgent) && navigator.maxTouchPoints > 1);
}

/** PC 화면에 띄우는 문자 QR. 휴대폰 카메라로 찍으면 번호와 내용이 채워진 채로 문자 앱이 열린다 (SMSTO: 형식).
 * 배포 주소 기준 약 220바이트라 61칸짜리 QR이 되고, 화면에 240px로 보여서 한 칸이 약 4px이다 */
function smsQr(number: string, text: string): Promise<string> {
  return QRCode.toDataURL(`SMSTO:${number}:${text}`, { errorCorrectionLevel: "M", margin: 2, width: 360 });
}

/** 승인한 영상의 시청 링크를 부모님께 보내는 버튼들 */
export function SharePanel({
  message,
  childName,
  phone,
  recipientId,
  onSent,
}: {
  message: Message;
  childName: string;
  phone?: string;
  /** 있으면 번호가 없을 때 이 화면에서 받는 분 번호를 대상자 정보에 저장할 수 있다 */
  recipientId?: number | null;
  onSent: (m: Message) => void;
}) {
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [canNativeShare, setCanNativeShare] = useState(false);
  const [kakaoKey, setKakaoKey] = useState<string | null>(null);
  // 서버 렌더링 때는 기기를 모르니 정해질 때까지 문자 버튼을 그리지 않는다
  const [mobile, setMobile] = useState<boolean | null>(null);
  const [number, setNumber] = useState(digitsOf(phone ?? ""));
  const [editingPhone, setEditingPhone] = useState(false);
  const [draft, setDraft] = useState("");
  const [savingPhone, setSavingPhone] = useState(false);
  const [qr, setQr] = useState<string | null>(null);
  useEffect(() => {
    setCanNativeShare("share" in navigator);
    setMobile(isMobileDevice());
    let active = true;
    void kakaoJsKey().then((key) => { if (active) setKakaoKey(key); });
    return () => { active = false; };
  }, []);
  useEffect(() => { setNumber(digitsOf(phone ?? "")); }, [phone]);
  const share = message.share!;
  const title = `${nameSubject(childName)} 영상 편지를 보냈어요`;
  // 문자는 받는 분이 휴대폰에서 바로 읽도록 짧게. 내 휴대폰에서 내 번호로 가서 스미싱으로 오해받지 않는다
  const smsText = `[온기] ${title}.\n눌러서 영상을 보고 답글을 남겨 주세요.\n${share.url}`;
  // "?&body="는 아이폰("&body=")과 안드로이드("?body=") 문자 앱이 모두 읽는 형태다
  const smsHref = `sms:${number}?&body=${encodeURIComponent(smsText)}`;
  const local = /localhost|127\.0\.0\.1/.test(share.url);
  const hasPhone = PHONE.test(number);

  const markSent = async (channel: string) => {
    onSent(await api<Message>(`/api/messages/${message.id}/sent`, { json: { channel } }));
  };

  const kakao = async () => {
    setError(null);
    try {
      const Kakao = await loadKakao();
      if (!Kakao.isInitialized()) Kakao.init(kakaoKey!);
      Kakao.Share.sendDefault({
        objectType: "text",
        text: `${title}\n눌러서 영상을 보고 답글을 남겨 주세요.`,
        link: { mobileWebUrl: share.url, webUrl: share.url },
        buttonTitle: "대화방 열기",
      });
      await markSent("kakao");
    } catch (e) {
      setError(e instanceof Error ? e.message : "카카오톡 공유에 실패했어요.");
    }
  };

  const nativeShare = async () => {
    try {
      await navigator.share({ title, text: `${title}\n로그인 없이 영상을 보고 답글을 남겨 주세요.`, url: share.url });
      await markSent("share");
    } catch {
      // 공유 창을 닫은 경우
    }
  };

  const copy = async () => {
    setError(null);
    try {
      await navigator.clipboard.writeText(share.url);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
      await markSent("copy");
    } catch (e) {
      setError(e instanceof Error ? e.message : "링크를 복사하지 못했어요. 아래 주소를 직접 복사해 주세요.");
    }
  };

  const openQr = async () => {
    setError(null);
    try {
      setQr(await smsQr(number, smsText));
    } catch {
      setError("QR 코드를 만들지 못했어요. 링크 복사하기로 보내 주세요.");
      return;
    }
    // 문자 버튼처럼, 보낼 준비를 연 시점에 보냄으로 남긴다 (실제 발송은 휴대폰에서 한다)
    await markSent("sms").catch((e) => setError(errorText(e)));
  };

  /** 받는 분 번호를 대상자 정보에 저장한다. 수정 API가 전체를 바꾸므로 지금 정보를 읽어 번호만 바꾼다 */
  const savePhone = async () => {
    const digits = digitsOf(draft);
    if (!PHONE.test(digits)) {
      setError("휴대폰 번호를 확인해 주세요. (예: 010-1234-5678)");
      return;
    }
    setError(null);
    setSavingPhone(true);
    try {
      const current = await api<Recipient>(`/api/recipients/${recipientId}`);
      const saved = await api<Recipient>(`/api/recipients/${recipientId}`, {
        method: "PUT",
        json: {
          nickname: current.nickname, relation: current.relation, phone: formatPhone(digits),
          child_call_name: current.child_call_name ?? "", speech_level: current.speech_level ?? "",
          tone_examples: current.tone_examples ?? "",
        },
      });
      setNumber(digitsOf(saved.phone));
      setEditingPhone(false);
      setQr(null);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setSavingPhone(false);
    }
  };

  const startEditPhone = () => {
    setDraft(hasPhone ? formatPhone(number) : "");
    setEditingPhone(true);
    setQr(null);
    setError(null);
  };

  let sms: React.ReactNode = null;
  if (mobile === null) {
    sms = null;
  } else if (editingPhone || !hasPhone) {
    sms = recipientId ? (
      <div className="space-y-3 rounded-2xl border border-stone-200 bg-white p-4">
        <label htmlFor={`sms-phone-${message.id}`} className="block text-sm font-bold text-stone-800">
          {hasPhone ? "문자를 받을 번호" : "문자로 보내려면 받는 분 휴대폰 번호를 넣어 주세요"}
        </label>
        <input
          id={`sms-phone-${message.id}`}
          type="tel"
          inputMode="numeric"
          autoComplete="tel"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") void savePhone(); }}
          placeholder="010-1234-5678"
          maxLength={13}
          className="w-full rounded-xl border border-stone-300 px-3 py-3 text-base outline-none focus:border-[#c8493c]"
        />
        <div className="flex gap-2">
          <Button onClick={savePhone} loading={savingPhone} disabled={!draft.trim()} className="flex-1">번호 저장하기</Button>
          {hasPhone && <Button variant="secondary" onClick={() => setEditingPhone(false)} disabled={savingPhone}>취소</Button>}
        </div>
        <p className="text-xs leading-5 text-stone-500">대상자 정보에 저장돼서 다음 영상 편지에도 써요. 문자는 내 휴대폰에서 내 번호로 보내요.</p>
      </div>
    ) : (
      <p className="rounded-2xl bg-stone-100 px-4 py-3 text-sm text-stone-600">대화방의 대상자 정보에 휴대폰 번호를 넣으면 문자로도 보낼 수 있어요.</p>
    );
  } else if (mobile) {
    sms = (
      <a
        href={smsHref}
        onClick={() => { void markSent("sms").catch(() => undefined); }}
        className="flex w-full items-center justify-center gap-2 rounded-2xl border border-stone-300 bg-white py-3.5 text-base font-bold text-stone-800"
      >
        <Smartphone className="h-5 w-5" /> 문자로 보내기 <span className="font-normal text-stone-500">({formatPhone(number)})</span>
      </a>
    );
  } else if (qr) {
    sms = (
      <div className="rounded-2xl border border-stone-200 bg-white p-4 text-center">
        {/* eslint-disable-next-line @next/next/no-img-element -- 브라우저에서 만든 data: 이미지라 최적화할 것이 없다 */}
        <img src={qr} alt={`${formatPhone(number)}에게 보낼 문자 QR 코드`} width={240} height={240} className="mx-auto h-60 w-60 [image-rendering:pixelated]" />
        <p className="mt-3 text-sm font-bold leading-6 text-stone-800">휴대폰 카메라로 찍어 주세요</p>
        <p className="mt-1 text-sm leading-6 text-stone-600">{formatPhone(number)}에게 보낼 문자가 채워진 채로 문자 앱이 열려요. 보내기만 누르면 돼요.</p>
        <button type="button" onClick={() => setQr(null)} className="mt-2 min-h-10 px-3 text-sm font-semibold text-stone-500 underline">QR 닫기</button>
      </div>
    );
  } else {
    sms = (
      <Button variant="secondary" onClick={openQr} className="w-full">
        <QrCode className="h-5 w-5" /> 휴대폰으로 문자 보내기 <span className="font-normal text-stone-500">({formatPhone(number)})</span>
      </Button>
    );
  }

  return (
    <div className="space-y-3">
      {local && (
        <Notice>
          지금 링크는 이 컴퓨터에서만 열려요. 부모님 휴대폰에서 열리게 하려면 backend/.env의 PUBLIC_BASE_URL을 배포
          주소나 터널(ngrok 등) 주소로 바꿔 주세요.
        </Notice>
      )}
      {error && <Notice tone="error">{error}</Notice>}

      {kakaoKey === null ? null : kakaoKey ? (
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

      {sms}
      {mobile !== null && hasPhone && !editingPhone && recipientId && (
        <p className="-mt-1 text-center">
          <button type="button" onClick={startEditPhone} className="min-h-9 px-2 text-xs font-semibold text-stone-500 underline">받는 번호 바꾸기</button>
        </p>
      )}

      <Button variant="secondary" onClick={copy} className="w-full">
        {copied ? <Check className="h-5 w-5 text-emerald-600" /> : <Copy className="h-5 w-5" />}
        {copied ? "복사했어요" : "링크 복사하기"}
      </Button>

      <p className="break-all rounded-xl bg-stone-100 px-3 py-2 text-xs text-stone-500">{share.url}</p>
      <p className="text-center text-sm leading-6 text-stone-500">이 링크로 로그인 없이 대화방에 들어가 영상을 보고 답글을 남길 수 있어요.</p>
      <p className="text-center text-xs text-stone-400">{formatDate(share.expires_at)}까지 대화방에 들어갈 수 있어요. 링크를 가진 분이 이 대상자의 대화 내역을 볼 수 있으니 받는 분께만 공유해 주세요.</p>
    </div>
  );
}
