import type { Caption, MessageStatus, Parent } from "./types";

export const CONVERSATION_TIMEZONE = "Asia/Seoul";

export type Recipient = Parent & {
  id: number;
  is_primary: boolean;
  video_count: number;
  reply_count: number;
  today_video_count: number;
  today_reply_count: number;
  last_activity_at: string | null;
  last_preview: string | null;
};

export type PublicRecipient = Pick<Recipient, "id" | "nickname" | "relation" | "child_name">;

export type ConversationMessage = {
  id: number;
  recipient_id: number;
  script: string;
  status: MessageStatus;
  duration: number | null;
  captions: Caption[] | null;
  video_url: string | null;
  poster_url: string | null;
  created_at: string;
  approved_at: string | null;
  sent_at: string | null;
  viewed_at: string | null;
  share?: { url: string; expires_at: string; view_count: number; first_viewed_at: string | null } | null;
};

export type ConversationVideoEvent = {
  type: "video";
  id: number;
  created_at: string;
  date: string;
  message: ConversationMessage;
};

export type ConversationReplyEvent = {
  type: "reply";
  id: number;
  created_at: string;
  date: string;
  text: string;
  message_id: number | null;
};

export type ConversationEvent = ConversationVideoEvent | ConversationReplyEvent;
export type ConversationDay = { date: string; video_count: number; reply_count: number };

export type ConversationThread = {
  recipient: Recipient | PublicRecipient;
  child_name: string;
  today: string;
  selected_date: string;
  timezone: "Asia/Seoul";
  days: ConversationDay[];
  events: ConversationEvent[];
  has_more: boolean;
  next_before: string | null;
  expires_at?: string;
  linked_message_id?: number;
  linked_date?: string;
};

/** 대화방 채팅: 대화가 있는 날 며칠씩. start~end가 이번에 받은 날짜 범위다 (대화가 없으면 null) */
export type ConversationFeed = {
  recipient: Recipient;
  child_name: string;
  today: string;
  timezone: "Asia/Seoul";
  days: ConversationDay[];
  events: ConversationEvent[];
  start: string | null;
  end: string | null;
  has_older: boolean;
  has_newer: boolean;
};

export type PublicConversationThread = ConversationThread;
export type PortfolioEvidence = { reply_id: number; text: string; date: string };
export type MonthlyPortfolio = {
  id: number;
  generated_at: string;
  source: "local_evidence_v1";
  title: string;
  summary: string;
  reply_count: number;
  active_days: number;
  days_in_month: number;
  topics: { name: string; count: number; evidence: PortfolioEvidence[] }[];
  daily_trends: { date: string; reply_count: number; characters: number; topics: string[] }[];
  representative_replies: PortfolioEvidence[];
  conversation_starters: string[];
  caveats: string[];
};

export type MonthlyPortfolioResponse = {
  recipient_id: number;
  month: string;
  available_months: string[];
  reply_count: number;
  active_days: number;
  stale: boolean;
  portfolio: MonthlyPortfolio | null;
};

/** Calendar boundaries are shared by owner and senior screens, irrespective of device time zone. */
export function kstDate(date: Date = new Date()): string {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: CONVERSATION_TIMEZONE,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(date);
  const value = (type: string) => parts.find((part) => part.type === type)?.value ?? "";
  return `${value("year")}-${value("month")}-${value("day")}`;
}

/** YYYY-MM-DD에서 며칠 앞뒤 날짜 (달력 날짜 계산이라 시간대와 무관하다) */
export function shiftDate(date: string, days: number): string {
  return new Date(Date.parse(`${date}T00:00:00Z`) + days * 86_400_000).toISOString().slice(0, 10);
}

export function kstMonth(date: Date = new Date()): string {
  return kstDate(date).slice(0, 7);
}

export function formatConversationDate(date: string): string {
  return new Intl.DateTimeFormat("ko-KR", {
    timeZone: CONVERSATION_TIMEZONE,
    year: "numeric",
    month: "long",
    day: "numeric",
    weekday: "short",
  }).format(new Date(`${date}T00:00:00+09:00`));
}

export function formatConversationTime(iso: string): string {
  return new Intl.DateTimeFormat("ko-KR", {
    timeZone: CONVERSATION_TIMEZONE,
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(iso));
}

export function formatConversationMonth(month: string): string {
  return `${Number(month.slice(0, 4))}년 ${Number(month.slice(5, 7))}월`;
}

export function mergeConversationEvents(...groups: ConversationEvent[][]): ConversationEvent[] {
  const events = new Map<string, ConversationEvent>();
  for (const group of groups) for (const event of group) events.set(`${event.type}-${event.id}`, event);
  const fraction = (timestamp: string) => (timestamp.match(/\d{2}:\d{2}:\d{2}(?:\.(\d+))?/)?.[1] ?? "").padEnd(6, "0");
  return Array.from(events.values()).sort((a, b) =>
    Date.parse(a.created_at) - Date.parse(b.created_at)
    || fraction(a.created_at).localeCompare(fraction(b.created_at))
    || a.type.localeCompare(b.type)
    || a.id - b.id,
  );
}

export function portfolioAsText(report: MonthlyPortfolioResponse, recipientName: string): string {
  const p = report.portfolio;
  if (!p) return "";
  return [
    `${recipientName} · ${formatConversationMonth(report.month)} 대화 포트폴리오`,
    p.title,
    p.summary,
    `답글 ${p.reply_count}개 / 대화한 날 ${p.active_days}일`,
    "",
    "자주 나눈 이야기",
    ...p.topics.map((topic) => `${topic.name} (${topic.count}회)\n${topic.evidence.map((e) => `  ${e.date} · ${e.text}`).join("\n")}`),
    "",
    "날짜별 답글",
    ...p.daily_trends.map((day) => `${day.date} · 답글 ${day.reply_count}개 · ${day.characters}자${day.topics.length ? ` · ${day.topics.join(", ")}` : ""}`),
    "",
    "기억할 답글",
    ...p.representative_replies.map((e) => `${e.date} · ${e.text}`),
    "",
    "다음 대화에 건넬 말",
    ...p.conversation_starters,
    "",
    ...p.caveats,
    `작성: ${p.generated_at}${report.stale ? " (새 답글이 있어 다시 분석이 필요합니다.)" : ""}`,
  ].join("\n");
}
