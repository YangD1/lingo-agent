import { api } from "./api";
import { practiceSetHref } from "./practice";
import { browserTimeZone } from "./vocab";

/** backend/app/adaptive/daily_plan/algorithm.py ItemKind, in the order items are shown. */
export const ITEM_KINDS = ["review", "practice", "new_words", "reading", "writing", "speaking"] as const;
export type ItemKind = (typeof ITEM_KINDS)[number];

/** The counts and switches of a plan (PlanChoice); what the learner adjusts. */
export type PlanChoice = {
  review: number;
  new_words: number;
  practice: boolean;
  reading: boolean;
  writing: boolean;
  /** Never drafted: the learner or the tutor adds it (Q59d). */
  speaking: boolean;
};

/** What a plan may be adjusted to, from when it was drafted (Q48c). */
export type PlanLimits = {
  reviews_due: number;
  new_left: number;
  practice: boolean;
  reading: boolean;
  max_count: number;
  /** Minutes of speaking that complete the speaking item; absent on older tutor cards. */
  speaking_minutes?: number;
};

export type Estimates = Record<ItemKind, number>;

type Named = { id: string; name_en: string; name_zh: string };

export type PlanItem = {
  kind: ItemKind;
  minutes: number;
  /** Reviews and new words; minutes to speak for speaking; null for the one-off items. */
  count: number | null;
  done: number;
  target: number;
  complete: boolean;
  kc: Named | null;
  article: { id: number; title: string } | null;
};

export type PlanStatus = "proposed" | "applied" | "declined";

/** backend/app/api/plan.py PlanOut. */
export type Plan = {
  id: string;
  day: string;
  status: PlanStatus;
  /** The tutor's card this plan came from; it is undone on that card. */
  card_id: string | null;
  choice: PlanChoice;
  items: PlanItem[];
  minutes: number;
  budget: number;
  budget_set: boolean;
  limits: PlanLimits;
  estimates: Estimates;
};

/** A tutor's daily plan card's params (backend/app/adaptive/daily_plan/card.py). */
export type PlanCardParams = {
  plan_id: string;
  day: string;
  choice: PlanChoice;
  items: { kind: ItemKind; minutes: number; count: number | null; ref: string | number | null }[];
  minutes: number;
  limits: PlanLimits;
  estimates: Estimates;
};

export function fetchPlan(): Promise<Plan> {
  const tz = browserTimeZone();
  const query = tz ? `?${new URLSearchParams({ tz })}` : "";
  return api<Plan>(`/plan/today${query}`);
}

export type PlanAction = "confirm" | "decline" | "undo";

/** 409 plan_not_pending / plan_not_applied / plan_from_card / plan_expired throw ApiError. */
export const decidePlan = (planId: string, action: PlanAction, choice?: PlanChoice) =>
  api<Plan>(`/plan/${encodeURIComponent(planId)}/${action}`, {
    method: "POST",
    json: { tz: browserTimeZone(), ...(choice ? { choice } : {}) },
  });

/** Estimated minutes of a choice, as the backend counts them. */
export function choiceMinutes(choice: PlanChoice, estimates: Estimates): number {
  return (
    choice.review * estimates.review +
    choice.new_words * estimates.new_words +
    (choice.practice ? estimates.practice : 0) +
    (choice.reading ? estimates.reading : 0) +
    (choice.writing ? estimates.writing : 0) +
    (choice.speaking ? estimates.speaking : 0)
  );
}

/** Keep a choice within what the plan allows, as the backend will. */
export function clampChoice(choice: PlanChoice, limits: PlanLimits): PlanChoice {
  const bound = (n: number, max: number) => Math.max(0, Math.min(Math.round(n), max, limits.max_count));
  return {
    review: bound(choice.review, limits.reviews_due),
    new_words: bound(choice.new_words, limits.new_left),
    practice: choice.practice && limits.practice,
    reading: choice.reading && limits.reading,
    writing: choice.writing,
    speaking: choice.speaking,
  };
}

/** Where to do an item. */
export function itemHref(item: Pick<PlanItem, "kind" | "kc" | "article">): string {
  switch (item.kind) {
    case "review":
    case "new_words":
      return "/vocab/review";
    case "practice":
      return practiceSetHref("plan", item.kc?.id);
    case "reading":
      return item.article ? `/reading/${item.article.id}` : "/reading";
    case "writing":
      return "/writing";
    case "speaking":
      return "/speaking";
  }
}
