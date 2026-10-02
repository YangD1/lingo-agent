import { api } from "@/lib/api";
import type { CefrLevel } from "@/lib/learner";
import type { KCName } from "@/lib/practice";

/** backend/app/api/writing.py; reviewed in the background, polled until done (Q38c). */
export type SubmissionStatus = "pending" | "done" | "failed";

export type WritingMistake = {
  kc_id: string;
  error_type: string;
  severity: "low" | "medium" | "high";
  /** The smallest wrong part, exactly as it is in the sentence. */
  original: string;
  correction: string;
  explanation: string;
};

/** One sentence of the text; `corrected` is null when it needed no change. */
export type SentenceCorrection = {
  index: number;
  paragraph: number;
  original: string;
  corrected: string | null;
  mistakes: WritingMistake[];
};

export const SCORE_NAMES = ["task", "coherence", "vocabulary", "grammar"] as const;
export type ScoreName = (typeof SCORE_NAMES)[number];
export type Score = { score: number; reason: string };

export type CollectedWord = { word_id: number; word: string; added: boolean };

export type Submission = {
  id: number;
  prompt: string;
  text: string;
  word_count: number;
  status: SubmissionStatus;
  error_code: string | null;
  corrections: SentenceCorrection[] | null;
  scores: Partial<Record<ScoreName, Score>> | null;
  summary: string | null;
  words: CollectedWord[] | null;
  model: string | null;
  from_conversation: boolean;
  /** The conversation it came from, while that still exists. */
  conversation_id: string | null;
  created_at: string;
  reviewed_at: string | null;
  kcs: KCName[];
};

export type SubmissionBrief = {
  id: number;
  prompt: string;
  excerpt: string;
  word_count: number;
  status: SubmissionStatus;
  mistakes: number;
  from_conversation: boolean;
  created_at: string;
};

export type WritingPrompt = { id: string; en: string; zh: string };
export type WritingPrompts = { level: CefrLevel; prompts: WritingPrompt[] };

export const submitWriting = (text: string, prompt: string) =>
  api<Submission>("/writing", { method: "POST", json: { text, prompt } });

export const fetchSubmission = (id: number | string) =>
  api<Submission>(`/writing/${encodeURIComponent(String(id))}`);

export const fetchSubmissions = () => api<SubmissionBrief[]>("/writing");

export const deleteSubmission = (id: number) =>
  api<void>(`/writing/${id}`, { method: "DELETE" });

export const fetchWritingPrompts = (level?: CefrLevel) =>
  api<WritingPrompts>(`/writing/prompts${level ? `?level=${level}` : ""}`);

// Q38f, the same limits as backend/app/writing/text.py.
export const MIN_WORDS = 20;
export const MAX_WORDS = 800;
export const MAX_CHARS = 6000;

// English words as the backend counts them: letters, with inner apostrophes and hyphens.
const WORD = /[A-Za-z]+(?:['’-][A-Za-z]+)*/g;

export function countWords(text: string): number {
  return text.match(WORD)?.length ?? 0;
}

/** Why the text can't be submitted yet, or null when it can. */
export function lengthProblem(text: string): "too_short" | "too_long" | null {
  if (text.length > MAX_CHARS) return "too_long";
  const words = countWords(text);
  if (words < MIN_WORDS) return "too_short";
  if (words > MAX_WORDS) return "too_long";
  return null;
}

/** The draft on /writing (Q39d): this browser only, cleared once submitted. */
const DRAFT_KEY = "lingo.writing.draft";
export type Draft = { text: string; prompt: string };

export function loadDraft(): Draft | null {
  try {
    const raw = window.localStorage.getItem(DRAFT_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<Draft>;
    return { text: String(parsed.text ?? ""), prompt: String(parsed.prompt ?? "") };
  } catch {
    return null;
  }
}

export function saveDraft(draft: Draft): void {
  try {
    if (draft.text.trim() || draft.prompt.trim()) {
      window.localStorage.setItem(DRAFT_KEY, JSON.stringify(draft));
    } else {
      window.localStorage.removeItem(DRAFT_KEY);
    }
  } catch {
    // Not saved: the text is still on the page.
  }
}

export function clearDraft(): void {
  try {
    window.localStorage.removeItem(DRAFT_KEY);
  } catch {
    // Nothing to clear.
  }
}

/** A piece of a sentence: plain, or the wrong part of the mistake at `mistake`. */
export type Piece = { text: string; mistake: number | null };

/**
 * The sentence cut around its mistakes' wrong parts, each at its first occurrence;
 * a part overlapping an earlier one, or not found, stays unmarked (its mistake is
 * still listed with the sentence).
 */
export function markMistakes(sentence: string, mistakes: WritingMistake[]): Piece[] {
  const spans: { start: number; end: number; mistake: number }[] = [];
  mistakes.forEach((m, i) => {
    const start = m.original ? sentence.indexOf(m.original) : -1;
    if (start < 0) return;
    const end = start + m.original.length;
    if (spans.some((s) => start < s.end && s.start < end)) return;
    spans.push({ start, end, mistake: i });
  });
  spans.sort((a, b) => a.start - b.start);
  const pieces: Piece[] = [];
  let at = 0;
  for (const s of spans) {
    if (s.start > at) pieces.push({ text: sentence.slice(at, s.start), mistake: null });
    pieces.push({ text: sentence.slice(s.start, s.end), mistake: s.mistake });
    at = s.end;
  }
  if (at < sentence.length) pieces.push({ text: sentence.slice(at), mistake: null });
  return pieces;
}

/** Sentences grouped by paragraph, in order. */
export function paragraphs(corrections: SentenceCorrection[]): SentenceCorrection[][] {
  const groups = new Map<number, SentenceCorrection[]>();
  for (const s of [...corrections].sort((a, b) => a.index - b.index)) {
    groups.set(s.paragraph, [...(groups.get(s.paragraph) ?? []), s]);
  }
  return [...groups.keys()].sort((a, b) => a - b).map((k) => groups.get(k)!);
}
