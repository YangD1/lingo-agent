import { api } from "@/lib/api";
import type { TutorCard } from "@/lib/cards";
import type { CefrLevel } from "@/lib/learner";
import type { Conversation } from "@/lib/types";

/** backend/app/adaptive/course.py LessonState (ADR 0044 §2). */
export type LessonState = "passed" | "review" | "learning" | "available" | "locked";

/** backend/app/api/course.py LessonOut. */
export type Lesson = {
  number: number;
  kc_id: string;
  name_en: string;
  name_zh: string;
  cefr: CefrLevel;
  state: LessonState;
  p_mastery: number;
  /** Share right in the latest finished pass quiz; null before one. */
  quiz_score: number | null;
  /** Prerequisites still to pass while the lesson is locked. */
  blocked_by: string[];
};

export type Course = {
  /** The learner's placement level; null before a placement test. */
  level: CefrLevel | null;
  /** The lesson to continue with; null once every lesson is passed. */
  current: string | null;
  pass_score: number;
  lessons: Lesson[];
};

export const fetchCourse = () => api<Course>("/course");

/** Start or continue a lesson; 409 lesson_locked for a locked one. */
export const startLesson = (kcId: string, locale: string) =>
  api<{ conversation: Conversation }>(`/course/lessons/${encodeURIComponent(kcId)}`, {
    method: "POST",
    json: { locale },
  });

/** "I already know this": a pass quiz card in the lesson's conversation; 409 quiz_limit. */
export const testOut = (kcId: string, locale: string) =>
  api<{ conversation: Conversation; card: TutorCard }>(
    `/course/lessons/${encodeURIComponent(kcId)}/test-out`,
    { method: "POST", json: { locale } },
  );

/** A test-out card's turn: it hangs under no message (ADR 0044 §5). */
export const isTestOutTurn = (turnId: string) => turnId.startsWith("test-out-");

/** Passed lessons over all, for "x / y". */
export function progress(course: Course): { passed: number; total: number } {
  const passed = course.lessons.filter((l) => l.state === "passed" || l.state === "review").length;
  return { passed, total: course.lessons.length };
}

/** The level shown open first: the current lesson's, else the learner's, else A2. */
export function openLevel(course: Course): CefrLevel {
  const current = course.lessons.find((l) => l.kc_id === course.current);
  return current?.cefr ?? course.level ?? "A2";
}

export const courseChatHref = (conversationId: string) =>
  `/chat?${new URLSearchParams({ c: conversationId })}`;

const lessonListeners = new Set<() => void>();

/** Something may have moved a lesson's state (a pass quiz finished, a turn ended): the
 * lesson bar reloads it. */
export function lessonChanged() {
  lessonListeners.forEach((listener) => listener());
}

export function onLessonChanged(listener: () => void): () => void {
  lessonListeners.add(listener);
  return () => void lessonListeners.delete(listener);
}
