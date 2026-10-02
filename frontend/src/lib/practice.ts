import { api } from "@/lib/api";
import type { CefrLevel, MasteryState } from "@/lib/learner";

/** backend/app/api/practice.py; formats from adaptive/exercise/formats.py. */
export const FORMATS = ["choice4", "cloze", "find_fix", "transform", "translate", "rewrite_own"] as const;
export type Format = (typeof FORMATS)[number];

export type KCName = { id: string; name_en: string; name_zh: string; cefr: CefrLevel | "" };

export type Content = {
  /** choice4, cloze: a sentence with one blank (___). */
  stem?: string;
  options?: string[];
  /** cloze: e.g. the verb to put in the right form. */
  hint?: string | null;
  /** find_fix: the sentence in pieces, joined as they are. */
  segments?: string[];
  /** transform, translate, rewrite_own: what to do. */
  instruction?: string | null;
  /** transform: the sentence to change; translate: the sentence to translate. */
  source?: string;
  /** rewrite_own: the learner's own sentence. */
  original?: string;
};

/** The item's key, sent once answered or reported. */
export type Key = {
  correct?: string;
  accepted?: string[];
  wrong_segment?: number;
  explanation: string;
};

export type OtherMistake = {
  kc_id: string;
  kc: KCName;
  error_type: string;
  severity: string;
  original: string;
  correction: string;
};

export type Feedback = {
  explanation: string;
  /** The grading model's correction of the learner's answer, if it graded one. */
  corrected: string | null;
  other_mistakes: OtherMistake[];
  model: string | null;
};

export type Reply =
  | { choice: string }
  | { text: string }
  | { segment: number; fix: string };

export type Result = {
  correct: boolean;
  response: Partial<{ choice: string; text: string; segment: number; fix: string }>;
  feedback: Feedback;
  created_at: string;
};

export type Item = {
  id: number;
  position: number;
  kc: KCName;
  format: Format;
  content: Content;
  status: "ok" | "reported";
  from_bank: boolean;
  answer: Key | null;
  result: Result | null;
};

export type Mastery = { p_mastery: number | null; state: MasteryState | null; learned: boolean };

export type KCChange = {
  kc: KCName;
  items: number;
  correct: number;
  before: Mastery;
  after: Mastery;
  progress: {
    formats_passed: string[];
    correct_span_hours: number;
    last_mistake_at: string | null;
    mastered_at: string | null;
    due: string | null;
  } | null;
};

export type HowMade = {
  written: number;
  from_bank: number;
  rejected: number;
  writers: string[];
  reviewers: string[];
};

export type SetStatus = "generating" | "ready" | "in_progress" | "done" | "failed";
export type Origin = "dashboard" | "learner" | "card" | "plan" | "practice";

export type PracticeSet = {
  id: string;
  status: SetStatus;
  /** While generating. */
  stage: "generating" | "reviewing" | "rewriting" | "filling" | null;
  origin: Origin | "prefetch";
  focus_kc: KCName | null;
  error_code: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  items: Item[];
  how_made: HowMade | null;
  /** Once done. */
  summary: { total: number; correct: number; kcs: KCChange[] } | null;
};

export type SetBrief = {
  id: string;
  status: SetStatus;
  origin: Origin | "prefetch";
  focus_kc: KCName | null;
  created_at: string;
  finished_at: string | null;
  total: number;
  answered: number;
  correct: number;
};

export type Answered = { item: Item; set_done: boolean };

/** Continue the unfinished set (for this grammar point, with `kcId`), or start one. */
export const startSet = (origin: Origin, kcId: string | null = null) =>
  api<PracticeSet>("/practice/sets", { method: "POST", json: { origin, kc_id: kcId } });

export const fetchSet = (id: string) => api<PracticeSet>(`/practice/sets/${encodeURIComponent(id)}`);

export const fetchRecentSets = () => api<SetBrief[]>("/practice/sets");

export const answerItem = (id: number, reply: Reply, latencyMs: number) =>
  api<Answered>(`/practice/exercises/${id}/answer`, {
    method: "POST",
    json: { ...reply, latency_ms: Math.max(0, Math.round(latencyMs)) },
  });

export const reportItem = (id: number) =>
  api<Answered>(`/practice/exercises/${id}/report`, { method: "POST", json: {} });

/** Items still to answer: shown, not reported, no result yet. */
export const openItems = (set: PracticeSet) =>
  set.items.filter((i) => i.status === "ok" && i.result === null);

export const isUnfinished = (status: SetStatus) =>
  status === "generating" || status === "ready" || status === "in_progress";

/** Link that starts (or continues) a set from an entry point; see PracticeApp. */
export function practiceSetHref(origin: Origin, kcId?: string | null): string {
  const params = new URLSearchParams({ from: origin });
  if (kcId) params.set("kc", kcId);
  return `/practice?${params}`;
}

/** The right answer as one line to show after answering. */
export function keyText(item: Item): string {
  const key = item.answer;
  if (!key) return "";
  if (item.format === "choice4") return key.correct ?? "";
  if (item.format === "find_fix" && item.content.segments && key.wrong_segment !== undefined) {
    const pieces = [...item.content.segments];
    pieces[key.wrong_segment] = key.accepted?.[0] ?? pieces[key.wrong_segment];
    return pieces.join("");
  }
  if (item.format === "cloze" && item.content.stem)
    return item.content.stem.replace(/_{2,}/, key.accepted?.[0] ?? "___");
  return key.accepted?.[0] ?? "";
}

/** The learner's answer as one line. */
export function replyText(item: Item, response: Result["response"]): string {
  if (response.choice !== undefined) return response.choice;
  if (response.segment !== undefined && item.content.segments) {
    const pieces = [...item.content.segments];
    pieces[response.segment] = response.fix ?? "";
    return pieces.join("");
  }
  return response.text ?? "";
}
