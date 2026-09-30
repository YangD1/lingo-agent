import { api } from "@/lib/api";
import type { CefrLevel } from "@/lib/learner";
import { browserTimeZone } from "@/lib/vocab";

/** backend/app/api/dashboard.py DashboardOut (P1 plan §7.5.1). */
export type Dashboard = {
  summary: {
    /** The profile's level: set by the placement test, editable by the learner. */
    cefr: CefrLevel | null;
    /** From the latest finished placement test. */
    vocab_size: number | null;
    vocab_cefr: CefrLevel | null;
    vocab_reliable: boolean | null;
    streak_days: number;
    studied_today: boolean;
    reviews_due: number;
    new_left: number;
  };
  /** Null until a word book is chosen; the four counts add up to `total`. */
  book: {
    id: string;
    name_zh: string;
    name_en: string;
    total: number;
    mastered: number;
    learning: number;
    known: number;
    unlearned: number;
  } | null;
  grammar: Record<CefrLevel, LevelSplit>;
  skills: SkillPoint[];
  errors: CommonError[];
  /** Oldest first, ending today in the learner's time zone. */
  days: Day[];
};

export type LevelSplit = {
  total: number;
  mastered: number;
  learning: number;
  weak: number;
  unseen: number;
};

export type SkillPoint = {
  skill: string;
  cefr: CefrLevel | null;
  /** 0–6 on one CEFR scale: A1 covers [0, 1) … C2 [5, 6]; null when it has no scale. */
  position: number | null;
  attempts: number;
  vocab_size: number | null;
  reliable: boolean | null;
};

export type CommonError = {
  kc_id: string;
  name_en: string;
  name_zh: string;
  cefr: CefrLevel;
  mistakes: number;
};

/** `date` is an ISO day (YYYY-MM-DD). */
export type Day = { date: string; reviews: number; turns: number };

export function fetchDashboard(): Promise<Dashboard> {
  const tz = browserTimeZone();
  return api<Dashboard>(tz ? `/dashboard?${new URLSearchParams({ tz })}` : "/dashboard");
}

/** Whether the learner has any grammar evidence at all. */
export const hasGrammar = (grammar: Dashboard["grammar"]) =>
  Object.values(grammar).some((l) => l.unseen < l.total);

export const hasActivity = (days: Day[]) => days.some((d) => d.reviews > 0 || d.turns > 0);

/** Heatmap shade 0–4: 0 is no activity, then quarters of the busiest day in view. */
export function intensity(day: Day, max: number): 0 | 1 | 2 | 3 | 4 {
  const total = day.reviews + day.turns;
  if (total === 0 || max === 0) return 0;
  return Math.min(4, Math.ceil((4 * total) / max)) as 1 | 2 | 3 | 4;
}

/**
 * The days as calendar columns, one per week, Monday first. The first week is padded
 * with nulls before the first day, the last after today.
 */
export function weeks(days: Day[]): (Day | null)[][] {
  if (days.length === 0) return [];
  // getUTCDay on a bare ISO date is that date's weekday; Monday = 0.
  const offset = (new Date(`${days[0].date}T00:00:00Z`).getUTCDay() + 6) % 7;
  const cells: (Day | null)[] = [...Array<null>(offset).fill(null), ...days];
  while (cells.length % 7) cells.push(null);
  const result: (Day | null)[][] = [];
  for (let i = 0; i < cells.length; i += 7) result.push(cells.slice(i, i + 7));
  return result;
}
