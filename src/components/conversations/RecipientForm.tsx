"use client";

import { useState, type FormEvent } from "react";
import { api, errorText } from "@/lib/api";
import type { Recipient } from "@/lib/conversations";
import type { Parent } from "@/lib/types";
import { Button, Notice } from "@/components/ui";

const INPUT = "mt-2 w-full rounded-xl border border-[#dce3d7] bg-[#fcfcf8] px-4 py-3 text-sm text-stone-800 outline-none focus:border-[#79967c] focus:ring-2 focus:ring-[#dce8d8]";

export function RecipientForm({ recipient, onSaved, onCancel }: {
  recipient?: Recipient;
  onSaved: (recipient: Recipient) => void;
  onCancel: () => void;
}) {
  const [nickname, setNickname] = useState(recipient?.nickname ?? "");
  const [relation, setRelation] = useState(recipient?.relation ?? "");
  const [phone, setPhone] = useState(recipient?.phone ?? "");
  const [callName, setCallName] = useState(recipient?.child_call_name ?? "");
  const [speechLevel, setSpeechLevel] = useState<Parent["speech_level"]>(recipient?.speech_level ?? "");
  const [tone, setTone] = useState(recipient?.tone_examples ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const prefix = recipient ? `recipient-${recipient.id}` : "new-recipient";

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (busy || !nickname.trim() || !relation.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const data = await api<Recipient>(recipient ? `/api/recipients/${recipient.id}` : "/api/recipients", {
        method: recipient ? "PUT" : "POST",
        json: {
          nickname: nickname.trim(), relation: relation.trim(), phone: phone.trim(),
          child_call_name: callName.trim(), speech_level: speechLevel, tone_examples: tone.trim(),
        },
      });
      onSaved(data);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="space-y-5">
      <div className="grid gap-5 sm:grid-cols-2">
        <label htmlFor={`${prefix}-nickname`} className="text-sm font-semibold">부르는 이름 <span className="text-[#a87662]">필수</span>
          <input id={`${prefix}-nickname`} value={nickname} onChange={(e) => setNickname(e.target.value)} maxLength={20} required autoComplete="off" placeholder="예: 엄마, 아버지, 김영희 님" className={INPUT} />
        </label>
        <label htmlFor={`${prefix}-relation`} className="text-sm font-semibold">나와의 관계 <span className="text-[#a87662]">필수</span>
          <input id={`${prefix}-relation`} value={relation} onChange={(e) => setRelation(e.target.value)} maxLength={20} required list={`${prefix}-relations`} placeholder="예: 어머니, 할아버지" className={INPUT} />
          <datalist id={`${prefix}-relations`}>{["어머니", "아버지", "할머니", "할아버지", "친척", "지인"].map((value) => <option key={value} value={value} />)}</datalist>
        </label>
        <label htmlFor={`${prefix}-phone`} className="text-sm font-semibold">연락처 <span className="font-normal text-stone-500">선택</span>
          <input id={`${prefix}-phone`} type="tel" value={phone} onChange={(e) => setPhone(e.target.value)} maxLength={20} autoComplete="tel" placeholder="010-1234-5678" className={INPUT} />
        </label>
        <label htmlFor={`${prefix}-call-name`} className="text-sm font-semibold">상대가 나를 부르는 이름 <span className="font-normal text-stone-500">선택</span>
          <input id={`${prefix}-call-name`} value={callName} onChange={(e) => setCallName(e.target.value)} maxLength={20} placeholder="예: 민수, 큰딸" className={INPUT} />
        </label>
      </div>
      <label htmlFor={`${prefix}-speech`} className="block text-sm font-semibold">영상 편지의 말투
        <select id={`${prefix}-speech`} value={speechLevel} onChange={(e) => setSpeechLevel(e.target.value as Parent["speech_level"])} className={INPUT}>
          <option value="">평소 쓰는 말투에 맞추기</option><option value="반말">반말</option><option value="존댓말">존댓말</option>
        </select>
      </label>
      <label htmlFor={`${prefix}-tone`} className="block text-sm font-semibold">평소 자주 하는 말 <span className="font-normal text-stone-500">선택</span>
        <textarea id={`${prefix}-tone`} value={tone} onChange={(e) => setTone(e.target.value)} maxLength={500} rows={3} placeholder="예: 엄마 밥 잘 챙겨 먹어. 주말에 또 전화할게!" className={`${INPUT} resize-y`} />
      </label>
      <p className="text-xs leading-6 text-stone-500">연락처를 입력하지 않아도 영상 편지를 만들고 대화방 링크를 공유할 수 있어요.</p>
      {error && <div role="alert"><Notice tone="error">{error}</Notice></div>}
      <div className="flex flex-wrap justify-end gap-2">
        <Button type="button" variant="ghost" onClick={onCancel} disabled={busy}>취소</Button>
        <Button type="submit" loading={busy} disabled={!nickname.trim() || !relation.trim()}>{recipient ? "정보 저장" : "대화 대상자 추가"}</Button>
      </div>
    </form>
  );
}
