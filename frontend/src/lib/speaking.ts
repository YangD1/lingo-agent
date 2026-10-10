import { api } from "@/lib/api";
import type { CefrLevel } from "@/lib/learner";

/** backend/app/api/speaking.py (ADR 0029). */
export type Scenario = {
  id: string;
  title_en: string;
  title_zh: string;
  levels: [CefrLevel, CefrLevel];
  learner_goal_en: string;
  learner_goal_zh: string;
  target_expressions: string[];
  /** Within its level range for me; the rest are shown folded (ADR 0029 §1). */
  suits: boolean;
};

export type Scenarios = { level: CefrLevel; scenarios: Scenario[] };

export type Intelligibility = "hard" | "partly" | "mostly" | "fully";

export type SpeakingSession = {
  id: string;
  conversation_id: string;
  /** null: free talk. */
  scenario_id: string | null;
  mode: "cascade" | "realtime";
  /** `failed`: the summary call failed; ending again retries it. */
  status: "active" | "done" | "failed";
  level: CefrLevel;
  turns: number;
  spoken_turns: number;
  spoken_seconds: number;
  intelligibility: Intelligibility | null;
  started_at: string;
  ended_at: string | null;
};

export type SpeakingSummary = {
  went_well: string[];
  mistakes: { quote: string; correction: string; explanation: string }[];
  more_natural: { quote: string; natural: string; note: string }[];
  next_expressions: { expression: string; meaning: string }[];
  intelligibility: Intelligibility;
};

export type SpeakingSessionDetail = SpeakingSession & {
  /** null until summed up, or when nothing was said. */
  summary: SpeakingSummary | null;
  /** Learner turns whose transcript was fixed and sent again (Q58b). */
  corrected_message_ids: string[];
};

export type SessionPage = { items: SpeakingSession[]; next_before: string | null };

export const fetchScenarios = () => api<Scenarios>("/speaking/scenarios");

export function fetchSessions(before?: string | null) {
  const params = new URLSearchParams();
  if (before) params.set("before", before);
  return api<SessionPage>(`/speaking/sessions${params.size ? `?${params}` : ""}`);
}

export const fetchSession = (id: string) => api<SpeakingSessionDetail>(`/speaking/sessions/${id}`);

export const startSession = (scenarioId: string | null, locale: string) =>
  api<SpeakingSessionDetail>("/speaking/sessions", {
    method: "POST",
    json: { scenario_id: scenarioId, locale },
  });

export const endSession = (id: string) =>
  api<SpeakingSessionDetail>(`/speaking/sessions/${id}/end`, { method: "POST" });

export const correctTranscript = (id: string, messageId: string) =>
  api<void>(`/speaking/sessions/${id}/corrections`, { method: "POST", json: { message_id: messageId } });

export const deleteSession = (id: string) => api<void>(`/speaking/sessions/${id}`, { method: "DELETE" });

/** The scenario's title in the UI's language; free talk has none. */
export const scenarioTitle = (scenario: Pick<Scenario, "title_en" | "title_zh">, locale: string) =>
  locale.startsWith("zh") ? scenario.title_zh : scenario.title_en;

export const scenarioGoal = (scenario: Pick<Scenario, "learner_goal_en" | "learner_goal_zh">, locale: string) =>
  locale.startsWith("zh") ? scenario.learner_goal_zh : scenario.learner_goal_en;
