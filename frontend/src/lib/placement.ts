import { api } from "@/lib/api";
import type { CefrLevel } from "@/lib/learner";

export type PlacementStage = "vocab" | "grammar";

/** The current question (backend/app/api/placement.py QuestionOut); no answer is in it. */
export type Question = {
  /** Sent back with the answer, so a stale page can't answer the wrong question. */
  id: string;
  stage: PlacementStage;
  /** 0-based within the stage. */
  index: number;
  /** Questions in the stage at most; the stage may end sooner. */
  total: number;
  /** vocab: "do you know this word?" */
  word?: string | null;
  /** grammar: a sentence with one blank (___) and four options. */
  stem?: string | null;
  options?: string[] | null;
};

export type PlacementResult = {
  /** Overall level: the grammar level. */
  cefr: CefrLevel;
  vocab: {
    size: number;
    half_known_rank: number;
    false_alarm: number;
    /** False when many pseudo-words were answered "known". */
    reliable: boolean;
    /** Rough level from the size alone (Milton 2010); not used for placement. */
    reference_cefr: CefrLevel | null;
  };
  grammar: { ability: number; standard_error: number; cefr: CefrLevel; answered: number };
};

export type Placement = {
  id: string;
  status: "in_progress" | "done" | "abandoned";
  stage: PlacementStage;
  answered: number;
  question: Question | null;
  result: PlacementResult | null;
  created_at: string;
  finished_at: string | null;
};

export type Answer = { yes: boolean } | { choice: number };

/** Continue the running test, or start one; `restart` abandons the running one first. */
export const startPlacement = (restart = false) =>
  api<Placement>("/placement", { method: "POST", json: { restart } });

export const fetchPlacement = (id: string) =>
  api<Placement>(`/placement/${encodeURIComponent(id)}`);

/** The most recent test in any state; null if the learner never started one. */
export const fetchLatestPlacement = () => api<Placement | null>("/placement/latest");

export const answerPlacement = (id: string, questionId: string, answer: Answer) =>
  api<Placement>(`/placement/${encodeURIComponent(id)}/answer`, {
    method: "POST",
    json: { question_id: questionId, ...answer },
  });

/** What the chat page's banner offers: nothing once a test is done. */
export function bannerFor(latest: Placement | null): "start" | "resume" | null {
  if (latest === null || latest.status === "abandoned") return "start";
  return latest.status === "in_progress" ? "resume" : null;
}

