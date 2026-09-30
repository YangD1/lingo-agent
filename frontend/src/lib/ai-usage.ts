import { api } from "@/lib/api";

/** Keys of backend/app/usage/features.yaml (ADR 0014). */
export type AiFeature =
  | "chat_message"
  | "chat_image"
  | "chat_pdf"
  | "chat_audio"
  | "practice_start"
  | "advice"
  | "memory_edit";

/** `llm_usage.task` labels the catalog uses; each has a name in messages (aiBadge.task). */
const AI_TASKS = [
  "chat",
  "chat_tools",
  "reflect",
  "memory",
  "vision",
  "asr",
  "practice_opening",
  "advice",
] as const;
export type AiTask = (typeof AI_TASKS)[number];

export function isAiTask(task: string): task is AiTask {
  return (AI_TASKS as readonly string[]).includes(task);
}

/** backend/app/api/usage.py CallEstimateOut. */
export type CallEstimate = {
  task: string;
  timing: "now" | "background";
  per: "call" | "image" | "page";
  input_tokens: number;
  output_tokens: number;
  /** Speech-to-text only: billed by audio length, not tokens. */
  audio_seconds: number | null;
  samples: number;
  /** history: this tenant's recent calls; default: no history yet. */
  source: "history" | "default";
  /** "<connection>:<model>" it would run on now; null when none is configured. */
  model: string | null;
};

export type UsageEstimates = {
  window: number;
  features: { feature: string; calls: CallEstimate[] }[];
};

// Averages move slowly; one request serves every badge for a while.
const TTL_MS = 5 * 60 * 1000;
let cached: { at: number; promise: Promise<UsageEstimates> } | null = null;

/** Shared by all badges; a failed request is not cached, so the next open retries. */
export function loadEstimates(now = Date.now()): Promise<UsageEstimates> {
  if (cached && now - cached.at < TTL_MS) return cached.promise;
  const promise = api<UsageEstimates>("/usage/estimates");
  const entry = { at: now, promise };
  cached = entry;
  promise.catch(() => {
    if (cached === entry) cached = null;
  });
  return promise;
}

export function resetEstimatesCache(): void {
  cached = null;
}

export function callsOf(estimates: UsageEstimates, feature: AiFeature): CallEstimate[] {
  return estimates.features.find((f) => f.feature === feature)?.calls ?? [];
}
