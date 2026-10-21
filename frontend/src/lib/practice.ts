import { api } from "@/lib/api";
import { elapsedMs } from "@/lib/elapsed";
import type { CefrLevel, MasteryState } from "@/lib/learner";

/** backend/app/api/practice.py; formats from adaptive/exercise/formats.py. */
export const FORMATS = [
  "choice4",
  "cloze",
  "find_fix",
  "transform",
  "translate",
  "rewrite_own",
  "concept_choice",
  "explain",
] as const;
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
  /** concept_choice, explain: a question about the rule, maybe in the learner's language
   * (understanding checks, ADR 0044 §3). */
  question?: string;
};

/** The item's key, sent once answered or reported. */
export type Key = {
  correct?: string;
  accepted?: string[];
  wrong_segment?: number;
  /** explain: what a good explanation covers. */
  key_points?: string[];
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
  /** explain only: how much of the rule the explanation got. */
  verdict?: "right" | "partly" | "wrong";
  missing?: string[];
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
  /** A quiz item whose answer the tutor gave away before it was answered: it counts
   * as wrong (task 95.3). */
  revealed: boolean;
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
  /** While generating (ADR 0048: each item is written on its own, so no "reviewing"). */
  stage: "generating" | "rewriting" | "filling" | null;
  /** quiz: a quiz card's set in the chat (ADR 0044 §4). */
  origin: Origin | "prefetch" | "quiz";
  focus_kc: KCName | null;
  error_code: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  /** Items planned, 0 until the plan is made. While generating, `items` holds those
   * already written, answerable at once (ADR 0048). */
  planned: number;
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

const quizListeners = new Set<() => void>();

/** A tutor turn ended: its reply may have given away a quiz answer (task 95.3), so
 * the quiz cards reload their sets. */
export function quizzesChanged() {
  quizListeners.forEach((listener) => listener());
}

export function onQuizzesChanged(listener: () => void): () => void {
  quizListeners.add(listener);
  return () => void quizListeners.delete(listener);
}

export const fetchSet = (id: string) => api<PracticeSet>(`/practice/sets/${encodeURIComponent(id)}`);

export const fetchRecentSets = () => api<SetBrief[]>("/practice/sets");

export const answerItem = (id: number, reply: Reply, latencyMs: number) =>
  api<Answered>(`/practice/exercises/${id}/answer`, {
    method: "POST",
    json: { ...reply, latency_ms: elapsedMs(latencyMs) },
  });

export const reportItem = (id: number) =>
  api<Answered>(`/practice/exercises/${id}/report`, { method: "POST", json: {} });

/** Items still to answer: shown, not reported, no result yet. */
export const openItems = (set: PracticeSet) =>
  set.items.filter((i) => i.status === "ok" && i.result === null);

/** The first item still open, by position; null when none is. */
export const firstOpenId = (set: PracticeSet): number | null => openItems(set)[0]?.id ?? null;

/**
 * Number and count for an item on show: items are numbered in the order they are
 * answered or reported, since while a set is written they need not arrive in order
 * (ADR 0048). The count is the plan's while the rest are still being written.
 */
export function itemPlace(set: PracticeSet, item: Item): { index: number; total: number } {
  const done = (i: Item) => i.result !== null || i.status !== "ok";
  const index = set.items.filter((i) => done(i) && i.id !== item.id).length;
  const total = set.status === "generating" ? Math.max(set.planned, set.items.length) : set.items.length;
  return { index, total };
}

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
  if (item.format === "choice4" || item.format === "concept_choice") return key.correct ?? "";
  if (item.format === "explain") return "";
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
