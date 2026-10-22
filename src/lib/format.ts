export function hasBatchim(word: string): boolean {
  const code = word.charCodeAt(word.length - 1);
  if (code >= 0xac00 && code <= 0xd7a3) return (code - 0xac00) % 28 !== 0;
  return false;
}

/** 준하 -> 준하가, 민준 -> 민준이가 */
export function nameSubject(name: string): string {
  return name + (hasBatchim(name) ? "이가" : "가");
}

export function formatSeconds(sec: number): string {
  const s = Math.max(0, Math.round(sec));
  const m = Math.floor(s / 60);
  return m ? `${m}분 ${s % 60}초` : `${s}초`;
}

export function formatDate(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  const now = new Date();
  const sameDay = d.toDateString() === now.toDateString();
  const time = d.toLocaleTimeString("ko-KR", { hour: "numeric", minute: "2-digit" });
  if (sameDay) return `오늘 ${time}`;
  return `${d.getMonth() + 1}월 ${d.getDate()}일 ${time}`;
}

/** S3Gen 음색 학습 상태. 학습 결과가 나쁘거나 실패해도 기본 목소리로 계속 쓸 수 있다 */
export const TUNING_LABEL: Record<string, string> = {
  queued: "목소리를 더 닮게 다듬는 중이에요 (5분쯤 걸려요)",
  training: "목소리를 더 닮게 다듬는 중이에요 (5분쯤 걸려요)",
  applied: "내 목소리에 맞게 다듬었어요",
  skipped: "기본 목소리를 쓰고 있어요",
  failed: "기본 목소리를 쓰고 있어요",
};

export const STATUS_LABEL: Record<string, string> = {
  draft: "대본 작성 중",
  generating: "영상 만드는 중",
  ready: "미리보기 준비됨",
  failed: "만들기 실패",
  approved: "승인됨 · 보내기 전",
  sent: "보냄",
  viewed: "시청함",
};
