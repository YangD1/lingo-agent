// Response shapes of the backend API (backend/app/api/*).

export type User = { id: string; email: string; display_name: string | null };
export type Tenant = { id: string; name: string; kind: string };
export type Me = { user: User; tenant: Tenant };

export type Conversation = {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  /** The grammar point a practice conversation is about; null for free chat. */
  focus_kc: { id: string; name_en: string; name_zh: string; cefr: string } | null;
  /** "planning": the study-planning conversation from the placement result (ADR 0015 §6). */
  purpose: "planning" | null;
};
export type AttachmentKind = "image" | "audio" | "document";
/** backend/app/api/attachments.py AttachmentOut (ADR 0008). */
export type Attachment = {
  id: string;
  conversation_id: string;
  kind: AttachmentKind;
  mime_type: string;
  filename: string;
  size_bytes: number;
  status: "processing" | "ready" | "failed";
  /** Derived text: the image reading, the transcript or the document's text. */
  text: string | null;
  meta: {
    progress?: { done: number; total: number } | null;
    error_message?: string;
    truncated?: boolean;
    [key: string]: unknown;
  };
  /** Failure code, e.g. no_vision_model or processing_failed. */
  error: string | null;
  sent: boolean;
  created_at: string;
};
export type HistoryMessage = {
  id: string | null;
  role: "user" | "assistant";
  content: string;
  attachments: Attachment[];
};

export const PROVIDER_KINDS = ["deepseek", "anthropic", "openai", "openai_compatible"] as const;
export type ProviderKind = (typeof PROVIDER_KINDS)[number];
export type Preset = {
  name: string;
  kind: ProviderKind;
  label: string | null;
  base_url: string;
  models: string[];
};
export type Presets = { presets: Preset[]; allow_private_networks: boolean };
export type Connection = {
  id: string;
  name: string;
  kind: ProviderKind;
  base_url: string;
  has_api_key: boolean;
  key_hint: string | null;
  params: Record<string, unknown>;
  enabled: boolean;
  default_model: string | null;
  last_verified_at: string | null;
  last_error: string | null;
};
export type TestPurpose = "chat" | "asr" | "vision";
export type ConnectionTest = {
  ok: boolean;
  error: string | null;
  // Set when the UI can explain the failure itself, e.g. "asr_not_supported".
  error_code: string | null;
  latency_ms: number;
  // A speech-to-text model is tested by transcribing a short clip, a vision one with a
  // small image; the backend guesses when the request doesn't say.
  purpose: TestPurpose;
};
export type TaskRoute = {
  section: "llm" | "embedding" | "asr";
  task: string;
  models: string[];
  params: Record<string, unknown>;
  overridden: boolean;
  // What actually runs now and which layer it came from (ADR 0007 §3).
  effective: string[];
  effective_source: "override" | "default" | "auto" | null;
};
export type DiscoveredModel = { id: string; category: "chat" | "embedding" | "other" };
export type ModelList = { models: DiscoveredModel[] };
export type UsageRow = {
  day: string;
  connection: string;
  model: string;
  calls: number;
  input_tokens: number;
  output_tokens: number;
  errors: number;
  fallbacks: number;
  avg_latency_ms: number;
};
export type Usage = { days: number; rows: UsageRow[] };

/** backend/app/memory/reflection.py EXAM_TAGS (the word books of ADR 0011). */
export const EXAMS = ["zk", "gk", "cet4", "cet6", "ky", "toefl", "ielts", "gre"] as const;
export type Exam = (typeof EXAMS)[number];
/** backend/app/api/memory.py ProfileOut (ADR 0009). */
export type Profile = {
  native_language: string | null;
  occupation: string | null;
  goal: string | null;
  target_exam: Exam | null;
  interests: string[];
  daily_minutes: number | null;
  explanation_language: "zh" | "en" | null;
  /** Set by assessment only, never edited here (ADR 0010). */
  cefr_level: string | null;
  timezone: string | null;
  /** Fields the learner set themselves: reflection leaves them alone. */
  manual_fields: string[];
};
export type MemoryKind = "fact" | "episode";
export type Memory = {
  id: string;
  kind: MemoryKind;
  content: string;
  source_conversation_id: string | null;
  source_title: string | null;
  created_at: string;
  updated_at: string;
};
