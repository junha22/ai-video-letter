import { Leaf, MessageCircle, Smile } from "lucide-react";
import type { VoiceCategory } from "@/lib/types";

// 공유 JSON과 저장된 이전 형식의 대본 모두 같은 안내 컴포넌트를 사용한다.
type GuidedScript = {
  kind: string;
  category?: string;
  hint?: string;
  guide?: string;
  focus?: readonly string[];
};

const CATEGORIES = {
  emotion: {
    label: "감정",
    Icon: Smile,
    detail: "감정 힌트 제시",
    description: "기쁨, 반가움, 걱정 등 여러 감정을 평소 말투에 담아요.",
    hint: "감정을 담아서",
    guide: "이 문장은 상대방에게 마음을 전하듯 읽어 주세요. 소리를 크게 내기보다 말투와 억양에 감정을 담아 주세요.",
  },
  calm: {
    label: "차분한 긴 문장",
    Icon: Leaf,
    detail: "참조 음성 후보",
    description: "편안한 속도와 일정한 목소리로 나의 기본 음색을 담아요.",
    hint: "차분하게",
    guide: "이 문장은 차분하고 편안한 목소리로 읽어 주세요. 쉼표에서 짧게 숨을 쉬고, 문장 끝까지 일정한 음량을 유지해 주세요.",
  },
  pronunciation: {
    label: "발음 커버리지",
    Icon: MessageCircle,
    detail: "발음별 확인",
    description: "받침과 여러 자음·모음을 자연스러운 문장 안에서 읽어요.",
    hint: "또박또박",
    guide: "이 문장은 발음에 신경 써서 또박또박 읽어 주세요. 음절을 끊거나 받침을 과장하지 말고, 평소 말하는 속도로 이어 주세요.",
  },
} as const;

export function voiceCategory(sentence: GuidedScript): VoiceCategory {
  if (sentence.category === "emotion" || sentence.category === "calm" || sentence.category === "pronunciation") {
    return sentence.category;
  }
  return sentence.kind === "calm" || sentence.kind === "statement" ? "calm" : "emotion";
}

export function VoiceCategoryOverview({ sentences }: { sentences: readonly GuidedScript[] }) {
  return (
    <section aria-label="녹음 대본 종류" className="mb-6">
      <h2 className="mb-2 text-sm font-bold text-[#3b5341]">여러 모습의 내 목소리를 담아요</h2>
      <p className="mb-4 text-xs leading-6 text-[#6b7767]">한 대본은 약 10초예요. 종류를 번갈아 읽고, 목표 시간을 채우면 마무리해요.</p>
      <div className="grid gap-3 sm:grid-cols-3">
        {(Object.keys(CATEGORIES) as VoiceCategory[]).map((category) => {
          const count = sentences.filter((sentence) => voiceCategory(sentence) === category).length;
          if (!count) return null;
          const { label, Icon, detail, description } = CATEGORIES[category];
          return (
            <div key={category} className="rounded-2xl border border-[#e3e8dc] bg-white px-4 py-4">
              <p className="flex items-center gap-2 text-sm font-bold text-[#3b5341]"><Icon size={16} className="shrink-0 text-[#63816a]" aria-hidden="true" />{label}</p>
              <p className="mt-2 text-xs font-semibold text-[#60735d]">대본 {count}개 · {detail}</p>
              <p className="mt-2 text-xs leading-6 text-[#6b7767]">{description}</p>
            </div>
          );
        })}
      </div>
    </section>
  );
}

export function VoiceScriptLabel({ sentence }: { sentence: GuidedScript }) {
  return (
    <p className="mb-5 flex flex-wrap items-center gap-2 text-xs font-semibold text-[#60785b]">
      <span className="rounded-full border border-[#dce5d6] bg-white px-3 py-1.5">{CATEGORIES[voiceCategory(sentence)].label}</span>
      <span>약 10초</span>
    </p>
  );
}

export function VoiceRecordingGuide({ sentence }: { sentence: GuidedScript }) {
  const category = voiceCategory(sentence);
  const { Icon, label, hint, guide } = CATEGORIES[category];
  return (
    <aside aria-label="이 대본 읽는 방법" className="rounded-[22px] border border-[#dfe7d8] bg-[#f1f5eb] p-5 sm:p-6">
      <p className="flex items-center gap-2 text-xs font-semibold text-[#60735d]"><Icon size={16} aria-hidden="true" />{label} · 읽는 방법</p>
      <h3 className="mt-3 text-lg font-bold text-[#344a38]">{sentence.hint || hint}</h3>
      <p className="mt-2 text-sm leading-7 text-[#53634d]">{sentence.guide || guide}</p>
      {category === "pronunciation" && Boolean(sentence.focus?.length) && (
        <div className="mt-4 border-t border-[#dce5d5] pt-4">
          <p className="mb-2 text-xs font-semibold text-[#53634d]">확인하는 발음</p>
          <ul className="flex flex-wrap gap-2">
            {sentence.focus?.map((focus) => <li key={focus} className="rounded-lg border border-[#dce5d5] bg-white px-2.5 py-1.5 text-xs text-[#476042]">{focus}</li>)}
          </ul>
        </div>
      )}
      {category === "calm" && <p className="mt-3 text-xs leading-6 text-[#60735d]">나의 기본 음색을 담는 참조 음성 후보예요.</p>}
      <p className="mt-3 text-xs leading-6 text-[#60735d]">안내는 읽지 않고, 대본만 녹음해 주세요.</p>
    </aside>
  );
}
