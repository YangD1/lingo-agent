import { api } from "@/lib/api";
import { type CefrLevel, practiceHref } from "@/lib/learner";
import type { ReminderReason } from "@/lib/placement";
import { browserTimeZone } from "@/lib/vocab";

export type AdviceKind =
  | "vocab_review"
  | "vocab_learn"
  | "vocab_screen"
  | "placement"
  | "grammar_practice"
  | "choose_book";

/** backend/app/api/advice.py AdviceItemOut: one of the learning engine's candidates (ADR 0016). */
export type AdviceItem = {
  candidate_id: string;
  kind: AdviceKind;
  /** Live evidence: due words, new words left, or mistakes. */
  count: number | null;
  /** Placement: days since the latest finished test; null if never. */
  days_since: number | null;
  in_progress: boolean;
  /** Placement (task 50): why to take it now; the last test's level and that level's
   * grammar points learned out of all. */
  reason: ReminderReason | null;
  level: CefrLevel | null;
  learned: number | null;
  total: number | null;
  kc: { id: string; name_en: string; name_zh: string; cefr: CefrLevel } | null;
  p_mastery: number | null;
  book: { id: string; name_en: string; name_zh: string } | null;
};

export type Advice = {
  /** Best first. */
  items: AdviceItem[];
  /** A chat model is set up: the tutor can talk the advice over; otherwise show links. */
  model_ready: boolean;
};

export function fetchAdvice(): Promise<Advice> {
  const tz = browserTimeZone();
  return api<Advice>(`/advice${tz ? `?${new URLSearchParams({ tz })}` : ""}`);
}

/** Which template text an item gets: placement splits by the reminder's reason. */
export function templateKey(item: AdviceItem) {
  if (item.kind !== "placement") return item.kind;
  if (item.in_progress) return "resume";
  if (item.reason === "progress") return "retest_progress";
  return item.days_since === null ? "placement" : "retest";
}

/** Where each advice leads. */
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
