import { useCallback, useEffect, useState } from "react";

import { type Advice, type AdviceItem, adviceHref, fetchAdvice, templateKey } from "@/lib/advice";
import type { PetActionOpens } from "@/lib/pet-actions";
import { fetchPlan, type Plan } from "@/lib/plan";
import { useOnReviewed } from "@/lib/vocab";

/**
 * The desk pet's own reminders (ADR 0039 §4). What to say comes from the learning engine
 * (`/advice`, already in order) and today's plan; here only when and how often. No model is
 * called. What was said today is kept on this device.
 */

/** Looked at again when the window regains focus, if older than this. */
const STALE_MS = 60_000;
/** At most this many reminders a day (the plan-done cheer doesn't count). */
export const MAX_PER_DAY = 3;
/** Between two reminders that weren't set off by something the learner did. */
export const MIN_GAP_MS = 10 * 60_000;
/** After arriving on a page, before the pet thinks of saying something. */
export const SETTLE_MS = 5_000;

export type NudgeKey =
  | "setupModel"
  | "vocab_review"
  | "vocab_learn"
  | "vocab_screen"
  | "choose_book"
  | "placement"
  | "retest"
  | "retest_progress"
  | "resume"
  | "grammar_practice"
  | "planPending"
  | "planLeft"
  | "afterReview"
  | "planDone";

/** One thing the pet could say; the bubble's words are `tutorPet.nudge.<key>`. */
export type Nudge = {
  /** Said at most once a day. */
  id: string;
  key: NudgeKey;
  values?: Record<string, string | number>;
  /** Starts with "Welcome back!" (after a doze). */
  welcome?: boolean;
  /** Where its button leads; none for a cheer. */
  href?: string;
  opens?: PetActionOpens;
};

export type NudgeLog = {
  /** The local day it is about (YYYY-MM-DD); another day starts empty. */
  day: string;
  /** Ids said today, in order. */
  said: string[];
  /** When the last reminder that counts was said (ms). */
  last: number;
};

export function today(now = new Date()): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

const LOG_KEY = "lingo.tutorPet.nudges";

export function readLog(day = today()): NudgeLog {
  const empty = { day, said: [], last: 0 };
  try {
    const found = JSON.parse(window.localStorage.getItem(LOG_KEY) ?? "null") as NudgeLog | null;
    if (!found || found.day !== day || !Array.isArray(found.said)) return empty;
    return { day, said: found.said.filter((s) => typeof s === "string"), last: Number(found.last) || 0 };
  } catch {
    return empty; // at worst a reminder too many today
  }
}

/** Notes `nudge` as said now; returns the log after. */
export function noteSaid(nudge: Nudge, now = Date.now(), day = today()): NudgeLog {
  const log = readLog(day);
  const counts = nudge.key !== "planDone";
  const after = {
    day,
    said: [...log.said, nudge.id],
    last: counts ? now : log.last,
  };
  try {
    window.localStorage.setItem(LOG_KEY, JSON.stringify(after));
  } catch {
    // Not kept: it may come again, which is harmless.
  }
  return after;
}

/**
 * Whether the pet may remind now: fewer than `MAX_PER_DAY` today, and `MIN_GAP_MS` since the
 * last unless the learner just did something (`event`).
 */
export function mayNudge(log: NudgeLog, now: number, event = false): boolean {
  const counted = log.said.filter((id) => id !== "plan_done").length;
  if (counted >= MAX_PER_DAY) return false;
  return event || now - log.last >= MIN_GAP_MS;
}

const pathOf = (href: string) => href.split(/[?#]/)[0];

function adviceNudge(item: AdviceItem, locale: string): Nudge {
  const key = templateKey(item);
  const href = adviceHref(item);
  const values: Record<string, string | number> = {};
  if (item.count !== null) values.n = item.count;
  if (item.days_since !== null) values.days = item.days_since;
  if (item.level) values.level = item.level;
  if (item.learned !== null) values.learned = item.learned;
  if (item.total !== null) values.total = item.total;
  if (item.kc) values.kc = locale.startsWith("zh") ? item.kc.name_zh : item.kc.name_en;
  return {
    id: `advice:${key}`,
    key,
    values,
    href,
    opens: pathOf(href) === "/vocab/review" ? "overlay" : "page",
  };
}

function planNudge(plan: Plan | null): Nudge | null {
  if (!plan) return null;
  if (plan.status === "proposed") {
    return { id: "plan", key: "planPending", href: "/dashboard", opens: "page" };
  }
  if (plan.status !== "applied") return null;
  const left = plan.items.filter((i) => !i.complete).length;
  if (left === 0) return null;
  return { id: "plan", key: "planLeft", values: { n: left }, href: "/dashboard", opens: "page" };
}

/**
 * What the pet would say now (ADR 0039 §4), or null: a chat model to set up first, else the
 * engine's first advice that isn't about the page the learner is on, else what is left of
 * today's plan. Each at most once a day (`said`).
 */
export function pickNudge({
  advice,
  plan,
  pathname,
  said,
  locale,
}: {
  advice: Advice | null;
  plan: Plan | null;
  pathname: string;
  said: readonly string[];
  locale: string;
}): Nudge | null {
  const fresh = (n: Nudge | null) =>
    n && !said.includes(n.id) && !(n.href && pathOf(n.href) === pathname) ? n : null;
  if (!advice) return null;
  if (!advice.model_ready) {
    const setup: Nudge = {
      id: "setup_model",
      key: "setupModel",
      href: "/settings#connections",
      opens: "setup",
    };
    // On the settings page itself there's nothing to lead to.
    return pathname === "/settings" || said.includes(setup.id) ? null : setup;
  }
  for (const item of advice.items) {
    const found = fresh(adviceNudge(item, locale));
    if (found) return found;
  }
  return fresh(planNudge(plan));
}

/**
 * After a round of flashcards: with nothing due any more and new words left, an offer to go
 * on with them. Null otherwise.
 */
export function afterReviewNudge(advice: Advice | null, said: readonly string[]): Nudge | null {
  if (!advice || said.includes("after_review")) return null;
  if (advice.items.some((i) => i.kind === "vocab_review")) return null;
  const learn = advice.items.find((i) => i.kind === "vocab_learn" && (i.count ?? 0) > 0);
  if (!learn) return null;
  return {
    id: "after_review",
    key: "afterReview",
    values: { n: learn.count ?? 0 },
    href: "/vocab/review?mode=new",
    opens: "overlay",
  };
}

export const PLAN_DONE_NUDGE: Nudge = { id: "plan_done", key: "planDone" };

/**
 * The learning engine's advice and today's plan for the pet: loaded while `on`, again after
 * a flashcards round and when the learner comes back to the window. Null until loaded, or
 * when they can't be had.
 */
export function usePetAdvice(on: boolean): {
  advice: Advice | null;
  plan: Plan | null;
  reload: () => void;
} {
  const [advice, setAdvice] = useState<Advice | null>(null);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [loadedAt, setLoadedAt] = useState(0);

  const reload = useCallback(() => {
    fetchAdvice().then(
      (found) => {
        setAdvice(found);
        setLoadedAt(Date.now());
      },
      () => {},
    );
    fetchPlan().then(setPlan, () => setPlan(null));
  }, []);

  useEffect(() => {
    if (on) reload();
  }, [on, reload]);

  useOnReviewed(
    useCallback(() => {
      if (on) reload();
    }, [on, reload]),
  );

  useEffect(() => {
    if (!on) return;
    const onFocus = () => {
      if (Date.now() - loadedAt > STALE_MS) reload();
    };
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, [on, loadedAt, reload]);

  return { advice: on ? advice : null, plan: on ? plan : null, reload };
}

/** The learner is typing somewhere: no bubble now. */
export function typing(): boolean {
  const el = document.activeElement;
  if (!(el instanceof HTMLElement)) return false;
  return el.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName);
}
