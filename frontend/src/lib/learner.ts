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
};

export type SkillEstimate = { skill: string; rating: number; attempts: number };

export type LearnerModel = {
  /** Weakest first. */
  kcs: KCStatus[];
  levels: Partial<Record<CefrLevel, { total: number; seen: number }>>;
  skills: SkillEstimate[];
  thresholds: { mastered: number; weak: number };
};

export type Evidence = {
  id: number;
  correct: boolean;
  evidence: "recognition" | "production";
  source: "chat" | "placement";
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
