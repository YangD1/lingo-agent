import { api } from "@/lib/api";

export const CEFR_LEVELS = ["A1", "A2", "B1", "B2", "C1", "C2"] as const;
export type CefrLevel = (typeof CEFR_LEVELS)[number];

export const MASTERY_STATES = ["weak", "learning", "mastered"] as const;
export type MasteryState = (typeof MASTERY_STATES)[number];

/** One grammar point the learner has met (backend/app/api/learner.py KCOut). */
export type KCStatus = {
  kc_id: string;
  name_en: string;
  name_zh: string;
  cefr: CefrLevel;
  p_mastery: number;
  state: MasteryState;
  /** Observations BKT used, and the correct ones among them by kind. */
  observations: number;
  recog_correct: number;
  produce_correct: number;
  /** Every stored mistake, including ones BKT left out. */
  mistakes: number;
  last_evidence_at: string | null;
  /** Progress towards "learned" (ADR 0021 §7): practice formats answered correctly,
   * hours between the first and last correct practice answer, and the latest counted
   * mistake in conversation or writing. */
  formats_passed: string[];
  correct_span_hours: number;
  last_mistake_at: string | null;
  /** Once learned: when, and when the grammar point is due for review. */
  mastered_at: string | null;
  due: string | null;
};

/** What "learned" takes (rules.yaml mastery_gate), besides mastery >= thresholds.mastered. */
export type MasteryGate = { min_formats: number; min_span_hours: number; clean_days: number };

export type SkillEstimate = {
  skill: string;
  rating: number;
  attempts: number;
  /** grammar: the level of its rating; vocab: the latest placement test's reference level. */
  cefr: CefrLevel | null;
  /** vocab only: the latest placement test's estimated size. */
  vocab_size: number | null;
  reliable: boolean | null;
};

export type LearnerModel = {
  /** Weakest first. */
  kcs: KCStatus[];
  levels: Partial<Record<CefrLevel, { total: number; seen: number }>>;
  skills: SkillEstimate[];
  thresholds: { mastered: number; weak: number };
  gate: MasteryGate;
};

export type Evidence = {
  id: number;
  correct: boolean;
  evidence: "recognition" | "production";
  source: "chat" | "placement" | "exercise";
  error_type: string | null;
  severity: "low" | "medium" | "high" | null;
  original: string | null;
  correction: string | null;
  l1_transfer: boolean;
  /** Whether BKT used it: low-severity slips and repeats within a turn are not used. */
  counted: boolean;
  /** Null once the conversation is deleted. */
  conversation_id: string | null;
  conversation_title: string | null;
  created_at: string;
};

export type EvidencePage = { evidence: Evidence[]; total: number };

export const fetchLearner = () => api<LearnerModel>("/learner");

export const fetchEvidence = (kcId: string) =>
  api<EvidencePage>(`/learner/kcs/${encodeURIComponent(kcId)}/evidence`);

export const deleteEvidence = (id: number) =>
  api<void>(`/learner/evidence/${id}`, { method: "DELETE" });

export const deleteLearner = () => api<{ deleted: number }>("/learner", { method: "DELETE" });

export type KCFilter = { level: CefrLevel | "all"; state: MasteryState | "all" };

export function filterKcs(kcs: KCStatus[], filter: KCFilter): KCStatus[] {
  return kcs.filter(
    (kc) =>
      (filter.level === "all" || kc.cefr === filter.level) &&
      (filter.state === "all" || kc.state === filter.state),
  );
}

export const kcName = (kc: { name_en: string; name_zh: string }, locale: string) =>
  locale.startsWith("zh") ? kc.name_zh : kc.name_en;

/** Link to a grammar point on the learner page, opened. */
export const learnerHref = (kcId: string) => `/learner?kc=${encodeURIComponent(kcId)}`;

/** Start (or return to an unstarted) practice conversation on a grammar point. */
export const practiceHref = (kcId: string) => `/chat?practice=${encodeURIComponent(kcId)}`;

export type LearnedCheck =
  | { key: "mastery"; met: boolean; value: number; target: number }
  | { key: "formats"; met: boolean; value: number; target: number }
  | { key: "span"; met: boolean; value: number; target: number }
  /** value: whole days since the latest counted mistake; null when there was none. */
  | { key: "clean"; met: boolean; value: number | null; target: number };

const DAY_MS = 24 * 60 * 60 * 1000;

/** The four conditions of "learned", as of `now`; mastery in whole percent. */
export function learnedChecks(
  kc: KCStatus,
  gate: MasteryGate,
  mastered: number,
  now: Date = new Date(),
): LearnedCheck[] {
  const sinceMistake =
    kc.last_mistake_at === null
      ? null
      : Math.floor((now.getTime() - new Date(kc.last_mistake_at).getTime()) / DAY_MS);
  return [
    {
      key: "mastery",
      met: kc.p_mastery >= mastered,
      value: Math.round(kc.p_mastery * 100),
      target: Math.round(mastered * 100),
    },
    {
      key: "formats",
      met: kc.formats_passed.length >= gate.min_formats,
      value: kc.formats_passed.length,
      target: gate.min_formats,
    },
    {
      key: "span",
      met: kc.correct_span_hours >= gate.min_span_hours,
      value: Math.floor(kc.correct_span_hours),
      target: gate.min_span_hours,
    },
    {
      key: "clean",
      met: sinceMistake === null || sinceMistake >= gate.clean_days,
      value: sinceMistake,
      target: gate.clean_days,
    },
  ];
}
