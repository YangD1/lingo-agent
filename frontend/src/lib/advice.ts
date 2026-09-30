import { api } from "@/lib/api";
import { type CefrLevel, practiceHref } from "@/lib/learner";
import { browserTimeZone } from "@/lib/vocab";

export type AdviceKind =
  | "vocab_review"
  | "vocab_learn"
  | "vocab_screen"
  | "placement"
  | "grammar_practice"
  | "choose_book";

/** backend/app/api/advice.py AdviceItemOut (P1 plan §7.5.2). */
export type AdviceItem = {
  candidate_id: string;
  kind: AdviceKind;
  /** Null: template advice, written here in the UI language. */
  title: string | null;
  reason: string | null;
  /** Live evidence: due words, new words left, or mistakes. */
  count: number | null;
  /** Placement: days since the latest finished test; null if never. */
  days_since: number | null;
  in_progress: boolean;
  kc: { id: string; name_en: string; name_zh: string; cefr: CefrLevel } | null;
  p_mastery: number | null;
  book: { id: string; name_en: string; name_zh: string } | null;
};

export type Advice = {
  items: AdviceItem[];
  /** ai / no_model / failed / empty; null before the first generation. */
  status: "ai" | "no_model" | "failed" | "empty" | null;
  generated_at: string | null;
  /** New advice is being written in the background. */
  refreshing: boolean;
  /** When "refresh" is allowed again; null = now. */
  refresh_after: string | null;
};

function query(locale: string): string {
  const tz = browserTimeZone();
  return new URLSearchParams({ locale, ...(tz ? { tz } : {}) }).toString();
}

export const fetchAdvice = (locale: string) => api<Advice>(`/advice?${query(locale)}`);

export const refreshAdvice = (locale: string) =>
  api<Advice>(`/advice/refresh?${query(locale)}`, { method: "POST" });

/** Where each advice leads. Grammar goes to the learner model until task 19's practice chat. */
export function adviceHref(item: AdviceItem): string {
  switch (item.kind) {
    case "vocab_review":
      return "/vocab/review";
    case "vocab_learn":
      return "/vocab/review?mode=new";
    case "vocab_screen":
      return "/vocab/screen";
    case "placement":
      return "/placement";
    case "choose_book":
      return "/vocab";
    case "grammar_practice":
      return item.kc ? practiceHref(item.kc.id) : "/learner";
  }
}

/** How long to keep asking while new advice is written: every 3 s, at most 10 times. */
export const POLL_MS = 3000;
export const POLL_TIMES = 10;
