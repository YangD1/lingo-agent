import { api } from "./api";

/** What the tutor did on a turn (ADR 0013 §3); `summary` depends on `name`. */
export type Activity = {
  turn_id: string;
  name: string;
  kind: "step" | "tool" | "mcp" | "background";
  call_id: string;
  status: "ok" | "failed" | "skipped";
  duration_ms: number | null;
  summary: Record<string, unknown>;
  created_at?: string;
};

export type ContextRead = {
  facts: string[];
  episodes: string[];
  profile_items: number;
  /** The grammar point of a practice conversation (P1 plan §7.5.3). */
  practice_kc?: string | null;
  /** A planning conversation: the placement result and advice candidates were read. */
  planning?: boolean;
  /** Where the learner stands now, counted by the app (ADR 0052 §1), was read. */
  progress?: boolean;
};
/** The supervisor gave a free-chat turn to another coach (ADR 0023 §3). */
export type Handoff = { coach: string };
/** writing_coach had the learner's text reviewed (task 38.5). */
export type WritingReviewed = { submission_id: number; mistakes: number };
/** reading_coach was given the article: its version's level, or null for the original. */
export type ReadingContextRead = { article_id: number; level: string | null; words: number };
/** The coach was given the document open in the workspace (ADR 0043 §6), its first words. */
export type WorkspaceContextRead = { doc_id: string; version: number; words: number };
/** The learner's writing, reviewed by writing_coach, opened in the workspace (ADR 0045 §4). */
export type WorkspaceOpened = { doc_id: string };
/** `deepen`: a follow-up under the reply (ADR 0064); a skipped or failed one has no summary. */
export type FollowUpWritten = {
  segment: number;
  trigger: "rule" | "model";
  outcome: "done" | "timeout" | "length" | "failed" | "no_start";
  reason?: string | null;
};
/** A tool call of the tutor (ADR 0015): the card it showed, if any. */
export type CardShown = { card_id: string | null; card_kind: string | null };
/** `load_skill`: the tutor read a built-in skill, or one of its parts (ADR 0055 §6). */
export type SkillLoaded = { skill: string; part?: string | null };
/** `lookup_word` on a realtime call: the entry found, or what was looked up in vain. */
export type WordLookedUp = { word: string; word_id?: number | null };
/** Activity names of a realtime call's tools (backend app/realtime/tools.py, Q61a–c). */
export const CALL_TOOL_NAMES = ["lookup_word", "add_to_vocab", "end_session"] as const;
/** Activity names of the tutor's tools (backend app/cards/tools.py). */
export const TOOL_NAMES = [
  "propose_word_book",
  "propose_learning_goal",
  "suggest_practice",
  "suggest_link",
  "give_quiz",
  "open_workspace",
  "propose_edit",
  "close_workspace",
  "set_workspace_auto_open",
  "withdraw_card",
  "load_skill",
] as const;
export type MemoryChanges = {
  added: string[];
  updated: string[];
  deleted: number;
  profile_fields: string[];
};
export type GrammarMistake = {
  kc_id: string;
  error_type: string;
  severity: "low" | "medium" | "high";
  original: string;
  correction: string | null;
};
export type GrammarTags = { mistakes: GrammarMistake[]; used_correctly: string[] };
export type SummaryUpdate = { episode_id: string | null };
/** `quiz_reveal`: a reply gave away answers of an unanswered pass quiz (task 95.3). */
export type AnswersRevealed = { kc_id: string; items: number };
export type CollectedWord = { word_id: number; word: string };
/** Words the learner asked about: put on their word list, or already had a card. */
export type WordsCollected = { added: CollectedWord[]; existing: CollectedWord[] };

export type MemoryRef = { kind: "fact" | "episode"; content: string };
export type KCRef = { name_en: string; name_zh: string; cefr: string };

export type ConversationActivity = {
  activities: Activity[];
  /** Referenced memories that still exist; a missing id was deleted. */
  memories: Record<string, MemoryRef>;
  kcs: Record<string, KCRef>;
  /** Collected words still on the learner's word list; the others were removed. */
  words_on_list: number[];
  /** Background work on the conversation is still queued or running. */
  pending: boolean;
};

export function fetchActivity(
  conversationId: string,
  turnIds: string[] = [],
  init?: RequestInit,
): Promise<ConversationActivity> {
  const query = new URLSearchParams(turnIds.map((t) => ["turn", t]));
  const suffix = turnIds.length ? `?${query}` : "";
  return api<ConversationActivity>(`/conversations/${conversationId}/activity${suffix}`, init);
}

/** A step recorded again (a retried reflection) replaces the earlier one. */
export function mergeActivities(current: Activity[], incoming: Activity[]): Activity[] {
  const key = (a: Activity) => `${a.name}\u0000${a.call_id}`;
  const merged = new Map(current.map((a) => [key(a), a]));
  for (const a of incoming) merged.set(key(a), a);
  return [...merged.values()];
}

export type TurnDigest = {
  memoriesRead: number;
  memoriesSaved: number;
  memoriesDeleted: number;
  /** The tutor was given a practice conversation's guidance. */
  practiced: boolean;
  /** The tutor was given a planning conversation's brief. */
  planned: boolean;
  /** The tutor was given the learner's progress, counted by the app. */
  progressRead: boolean;
  /** The coach a free-chat turn was handed to, if any. */
  handedTo: string | null;
  /** The learner's text was reviewed (writing_coach). */
  writingReviewed: boolean;
  /** reading_coach read the article (Q43i). */
  articleRead: boolean;
  /** The coach read the document open in the workspace. */
  workspaceRead: boolean;
  /** Cards the tutor showed with tool calls, and took back (ADR 0049). */
  cardsShown: number;
  cardsWithdrawn: number;
  /** Built-in skills the tutor read (ADR 0055 §6), each named once. */
  skillsRead: string[];
  /** Pass-quiz items whose answer a reply gave away, so they count as wrong. */
  answersRevealed: number;
  /** Follow-ups written under the reply (ADR 0064). */
  followUps: number;
  profileUpdated: boolean;
  mistakes: number;
  usedCorrectly: number;
  summaryUpdated: boolean;
  wordsCollected: number;
  /** Words the tutor looked up on a realtime call. */
  wordsLookedUp: number;
  /** Steps that failed or were skipped (no model configured). */
  failed: string[];
  skipped: string[];
};

/** The one-line summary shown under a reply. */
export function digest(activities: Activity[]): TurnDigest {
  const d: TurnDigest = {
    memoriesRead: 0,
    memoriesSaved: 0,
    memoriesDeleted: 0,
    practiced: false,
    planned: false,
    progressRead: false,
    handedTo: null,
    writingReviewed: false,
    articleRead: false,
    workspaceRead: false,
    cardsShown: 0,
    cardsWithdrawn: 0,
    skillsRead: [],
    answersRevealed: 0,
    followUps: 0,
    profileUpdated: false,
    mistakes: 0,
    usedCorrectly: 0,
    summaryUpdated: false,
    wordsCollected: 0,
    wordsLookedUp: 0,
    failed: [],
    skipped: [],
  };
  for (const a of activities) {
    // A follow-up not written is said under the reply itself, not as a step gone wrong.
    if (a.name === "deepen" && a.status !== "ok") continue;
    if (a.status === "failed") d.failed.push(a.name);
    if (a.status === "skipped") d.skipped.push(a.name);
    if (a.status !== "ok") continue;
    if (a.name === "load_context") {
      const s = a.summary as ContextRead;
      d.memoriesRead += (s.facts?.length ?? 0) + (s.episodes?.length ?? 0);
      d.practiced ||= Boolean(s.practice_kc);
      d.planned ||= Boolean(s.planning);
      d.progressRead ||= Boolean(s.progress);
    } else if (a.name === "handoff") {
      d.handedTo = (a.summary as Handoff).coach;
    } else if (a.name === "writing_review") {
      d.writingReviewed = true;
    } else if (a.name === "reading_context") {
      d.articleRead = true;
    } else if (a.name === "workspace_context") {
      d.workspaceRead = true;
    } else if (a.name === "lookup_word") {
      d.wordsLookedUp += 1;
    } else if (a.name === "add_to_vocab") {
      d.wordsCollected += (a.summary as WordsCollected).added?.length ?? 0;
    } else if (a.name === "withdraw_card") {
      if ((a.summary as CardShown).card_id) d.cardsWithdrawn += 1;
    } else if (a.name === "load_skill") {
      const { skill } = a.summary as SkillLoaded;
      if (skill && !d.skillsRead.includes(skill)) d.skillsRead.push(skill);
    } else if (a.kind === "tool") {
      if ((a.summary as CardShown).card_id) d.cardsShown += 1;
    } else if (a.name === "reflect_memory") {
      const s = a.summary as MemoryChanges;
      d.memoriesSaved += (s.added?.length ?? 0) + (s.updated?.length ?? 0);
      d.memoriesDeleted += s.deleted ?? 0;
      d.profileUpdated ||= (s.profile_fields?.length ?? 0) > 0;
    } else if (a.name === "grammar_tagging") {
      const s = a.summary as GrammarTags;
      d.mistakes += s.mistakes?.length ?? 0;
      d.usedCorrectly += s.used_correctly?.length ?? 0;
    } else if (a.name === "vocab_collect") {
      d.wordsCollected += (a.summary as WordsCollected).added?.length ?? 0;
    } else if (a.name === "summarize") {
      d.summaryUpdated = true;
    } else if (a.name === "deepen") {
      d.followUps += 1;
    } else if (a.name === "quiz_reveal") {
      d.answersRevealed += (a.summary as AnswersRevealed).items ?? 0;
    }
  }
  return d;
}
