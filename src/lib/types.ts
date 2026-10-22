export type Parent = {
  nickname: string;
  relation: string;
  phone: string;
  tone_examples: string;
};

export type VoiceSummary = {
  status: "none" | "recording" | "processing" | "ready" | "failed";
  total_seconds: number;
  target_seconds: number;
  error: string | null;
};

export type PhotoInfo = {
  width: number;
  height: number;
  face: [number, number, number, number];
  url: string;
};

export type Me = {
  user: { id: number; name: string; kakao: boolean };
  consent_ok: boolean;
  parent: Parent | null;
  voice: VoiceSummary;
  photo: PhotoInfo | null;
  can_write: boolean;
  can_render: boolean;
};

export type Job = {
  status: "queued" | "running" | "done" | "failed" | "canceled";
  stage: "tts" | "video" | "encode" | null;
  attempts: number;
  max_attempts: number;
  last_error: string | null;
  tts_provider: string | null;
  video_provider: string | null;
  gpu_seconds: number;
  cost_usd: number;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
};

export type Caption = { start: number; end: number; text: string };

export type MessageStatus = "draft" | "generating" | "ready" | "failed" | "approved" | "sent" | "viewed";

export type Message = {
  id: number;
  memo: string;
  template: string;
  template_label: string;
  script: string;
  script_source: "llm" | "fallback" | "edited";
  script_problems: string[];
  char_count: number;
  est_seconds: number;
  status: MessageStatus;
  error: string | null;
  duration: number | null;
  captions: Caption[] | null;
  video_url: string | null;
  poster_url: string | null;
  job: Job | null;
  share: { url: string; expires_at: string; view_count: number; first_viewed_at: string | null } | null;
  parent_nickname: string | null;
  created_at: string;
  approved_at: string | null;
  sent_at: string | null;
  viewed_at: string | null;
};

export type Sentence = {
  index: number;
  text: string;
  kind: "calm" | "statement" | "question" | "exclamation";
  sample: { duration: number; ok: boolean } | null;
};

export type VoiceState = {
  status: VoiceSummary["status"];
  error: string | null;
  total_seconds: number;
  target_seconds: number;
  sentences: Sentence[];
  job: Job | null;
};

export type ConsentState = {
  version: string;
  ok: boolean;
  items: { kind: "voice" | "face" | "parent_receive"; title: string; description: string; agreed_at: string | null }[];
};

export type NotificationItem = {
  id: number;
  kind: string;
  text: string;
  message_id: number | null;
  created_at: string;
  read: boolean;
};

export type WatchInfo = {
  child_name: string;
  nickname: string;
  created_at: string;
  duration: number | null;
  captions: Caption[];
  video_url: string;
  poster_url: string;
  expires_at: string;
  others: { token: string; created_at: string; preview: string }[];
};
