// Response shapes of the backend API (backend/app/api/*).

import type { AiFeature } from "@/lib/ai-usage";
import type { Capability, Limit, UNITS, Used } from "@/lib/org";

export type User = {
  id: string;
  email: string;
  display_name: string | null;
  /** Null until the setup guide is finished (ADR 0042); the app sends the learner there. */
  setup_completed_at: string | null;
};
export type Tenant = { id: string; name: string; kind: string };
export type Me = { user: User; tenant: Tenant };

export type Conversation = {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  /** The grammar point a practice conversation is about; null for free chat. */
  focus_kc: { id: string; name_en: string; name_zh: string; cefr: string } | null;
  /**
   * "planning": the study-planning conversation from the placement result (ADR 0015 §6);
   * "daily": the dashboard's conversation of the day (ADR 0016);
   * "speaking": a speaking practice, shown on /speaking only (ADR 0029);
   * "lesson": a lesson of the grammar course on `focus_kc` (ADR 0044 §5).
   */
  purpose: "planning" | "daily" | "speaking" | "lesson" | null;
  /** The article a reading conversation is about (Q43h); null otherwise or once it is gone. */
  article_id: number | null;
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

export const PROVIDER_KINDS = [
  "deepseek",
  "anthropic",
  "openai",
  "openai_compatible",
  "azure_speech",
  "gemini",
] as const;
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
export type TestPurpose = "chat" | "asr" | "vision" | "tts" | "pronunciation" | "realtime";
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
  section: "llm" | "embedding" | "asr" | "tts" | "pronunciation" | "realtime";
  task: string;
  models: string[];
  params: Record<string, unknown>;
  // Refs from `models` switched off: kept in the chain, never called (ADR 0026).
  disabled: string[];
  overridden: boolean;
  // What actually runs now and which layer it came from (ADR 0007 §3).
  effective: string[];
  effective_source: "override" | "default" | "auto" | null;
  /**
   * tts only: per "<connection>:<model>", the voice it reads each language with when
   * `params.voices` doesn't say; null: none, so that language goes to the next model.
   */
  default_voices?: Record<string, Record<VoiceLanguage, string | null>> | null;
  /** tts only: per "<connection>:<model>", the voices it offers to pick from (Q64q). */
  voice_options?: Record<string, VoiceOption[]> | null;
  /** The main account's name when its connections serve this task for a member (ADR 0031 §5). */
  provided_by?: string | null;
  /** ... and the member's quota for it is used up for now. */
  quota_exhausted?: boolean;
};
/** A voice a read-aloud model offers (backend/app/providers/tts_voices.py). */
export type VoiceOption = {
  /** What the route's `voices` store: a name, or for qwen-audio a description. */
  id: string;
  name: string;
  /** null: the vendor doesn't say (OpenAI's call voices). */
  gender: "female" | "male" | null;
  languages: VoiceLanguage[];
  accent: string | null;
  note: string;
};
/** The languages a read-aloud route has voices for (backend/app/providers/tts.py). */
export const VOICE_LANGUAGES = ["en-US", "en-GB", "zh-CN"] as const;
export type VoiceLanguage = (typeof VOICE_LANGUAGES)[number];
export type DiscoveredModel = { id: string; category: "chat" | "embedding" | "other" };
export type ModelList = { models: DiscoveredModel[] };
export type UsageRow = {
  day: string;
  connection: string;
  model: string;
  calls: number;
  input_tokens: number;
  output_tokens: number;
  /** Read-aloud is billed by characters; 0 for other calls. */
  characters: number;
  errors: number;
  fallbacks: number;
  avg_latency_ms: number;
  /** null: this account's own calls; else a member's on its connections (ADR 0031 §8). */
  member: string | null;
};
export type Usage = { days: number; rows: UsageRow[] };

/** backend/app/api/usage.py TallyOut (ADR 0034 §2). */
export type UsageTally = {
  calls: number;
  input_tokens: number;
  output_tokens: number;
  characters: number;
  audio_minutes: number;
  errors: number;
  fallbacks: number;
  /** In the tenant's currency; null: nothing in it was priced (ADR 0034 §3). */
  cost: number | null;
  /** Some usage in it had no price, so `cost` leaves it out. */
  cost_partial: boolean;
};
export type UsageDashboard = {
  days: number;
  total: UsageTally;
  series: (UsageTally & { day: string })[];
  tasks: (UsageTally & { task: string; background: boolean })[];
  models: (UsageTally & { connection: string; model: string })[];
  members: (UsageTally & { member: string | null })[];
  /** Some call was priced: show costs at all. */
  priced: boolean;
  currency: PriceCurrency;
};
export const PRICE_CURRENCIES = ["CNY", "USD"] as const;
export type PriceCurrency = (typeof PRICE_CURRENCIES)[number];
/** backend/app/api/usage.py ModelPriceIO: per million tokens, thousand characters, minute. */
export type ModelPrice = {
  connection: string;
  model: string;
  input_per_mtok: number | null;
  output_per_mtok: number | null;
  per_kchar: number | null;
  per_minute: number | null;
};
export type Prices = { currency: PriceCurrency; prices: ModelPrice[] };
/** backend/app/api/usage.py MyUsageOut (ADR 0034 §4). */
export type MyUsage = {
  month_start: string;
  sponsor_name: string | null;
  capabilities: {
    capability: Capability;
    unit: (typeof UNITS)[Capability];
    month: number;
    /** Only for a member: their quota from the main account. left: null = no cap. */
    quota: (Limit & Used & { left: number | null }) | null;
  }[];
};

/** backend/app/memory/reflection.py EXAM_TAGS (the word books of ADR 0011). */
export const EXAMS = ["zk", "gk", "cet4", "cet6", "ky", "toefl", "ielts", "gre"] as const;
export type Exam = (typeof EXAMS)[number];
/** backend/app/api/memory.py ProfileOut (ADR 0009). */
export type ChatLanguage = "zh" | "en";
export type Profile = {
  native_language: string | null;
  occupation: string | null;
  goal: string | null;
  target_exam: Exam | null;
  interests: string[];
  daily_minutes: number | null;
  explanation_language: "zh" | "en" | null;
  /** Which language the tutor mainly talks in; null: picked by level (ADR 0017 §1). */
  chat_language: ChatLanguage | null;
  /** What applies now: the choice, or the level's default. */
  chat_language_effective: ChatLanguage;
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

/** backend/app/api/background.py (ADR 0025 §5-6). */
export type BudgetState = "ok" | "exhausted" | "off";
export type BackgroundFeature = {
  key: string;
  enabled: boolean;
  default: boolean;
  usage_feature: AiFeature;
};
export type MyBackground = { features: BackgroundFeature[]; budget: BudgetState };
export type SchedulerJob = {
  job: string;
  next_run_at: string | null;
  last_started_at: string | null;
  last_finished_at: string | null;
  last_success_at: string | null;
  last_status: "running" | "ok" | "skipped" | "error" | null;
  last_skip_reason: string | null;
  last_error: string | null;
};
/** backend/app/api/word_audio.py (ADR 0028 §4). */
export type WordAudioAccent = "en-US" | "en-GB";
export type WordAudioVoice = { connection: string; model: string; voice: string };
export type WordAudioJob = {
  id: string;
  book_id: string;
  status: "running" | "paused" | "done" | "cancelled";
  voices: Partial<Record<WordAudioAccent, WordAudioVoice>>;
  requests_per_minute: number;
  price_per_million: number | null;
  currency: string | null;
  total: number;
  done: number;
  failed: number;
  characters: number;
  bytes: number;
  cost: number | null;
  error: string | null;
  created_at: string;
  finished_at: string | null;
};
export type WordAudioBook = {
  book_id: string;
  name_zh: string;
  name_en: string;
  words: number;
  made: Record<WordAudioAccent, number>;
};
export type WordAudio = {
  available: boolean;
  voices: Partial<Record<WordAudioAccent, WordAudioVoice>>;
  job: WordAudioJob | null;
  books: WordAudioBook[];
  count: number;
  bytes: number;
  old_count: number;
  old_bytes: number;
};
export type WordAudioEstimate = {
  book_id: string;
  words: number;
  voices: Partial<Record<WordAudioAccent, WordAudioVoice>>;
  missing: WordAudioAccent[];
  pieces: number;
  existing: number;
  characters: number;
  bytes: number;
  cost: number | null;
  requests_per_minute: number;
  suggested_price: number | null;
  /** One word's time on a model slow enough to set the pace (qwen-audio); null: the pace does. */
  seconds_per_word: number | null;
  minutes: number;
};
export type RealtimeLimits = {
  session_minutes: number;
  daily_minutes: number;
  // The signed-in admin's own minutes today (UTC).
  used_minutes: number;
  state: "ok" | "used_up" | "off";
};

export type TenantBackground = {
  daily_tokens: number;
  used_today: number;
  budget: BudgetState;
  scheduler_running: boolean;
  jobs: SchedulerJob[];
};
