import { afterEach, describe, expect, it } from "vitest";

import type { Advice, AdviceItem } from "./advice";
import {
  afterReviewNudge,
  MAX_PER_DAY,
  mayNudge,
  MIN_GAP_MS,
  noteSaid,
  pickNudge,
  PLAN_DONE_NUDGE,
  readLog,
  today,
} from "./pet-nudges";
import type { Plan, PlanItem } from "./plan";

const item = (kind: AdviceItem["kind"], extra: Partial<AdviceItem> = {}): AdviceItem => ({
  candidate_id: kind,
  kind,
  count: null,
  days_since: null,
  in_progress: false,
  reason: null,
  level: null,
  learned: null,
  total: null,
  kc: null,
  p_mastery: null,
  book: null,
  ...extra,
});

const advice = (items: AdviceItem[], model_ready = true): Advice => ({ items, model_ready });

const plan = (status: Plan["status"], complete: boolean[]): Plan =>
  ({
    status,
    items: complete.map((c) => ({ kind: "review", complete: c }) as PlanItem),
  }) as Plan;

const pick = (
  a: Advice | null,
  extra: { plan?: Plan | null; pathname?: string; said?: string[]; locale?: string } = {},
) =>
  pickNudge({
    advice: a,
    plan: extra.plan ?? null,
    pathname: extra.pathname ?? "/dashboard",
    said: extra.said ?? [],
    locale: extra.locale ?? "en",
  });

afterEach(() => window.localStorage.clear());

describe("pickNudge", () => {
  it("leads to model setup first, except on the settings page", () => {
    const none = advice([item("vocab_review", { count: 5 })], false);
    expect(pick(none)).toMatchObject({
      id: "setup_model",
      href: "/settings#connections",
      opens: "setup",
    });
    expect(pick(none, { pathname: "/settings" })).toBeNull();
    expect(pick(none, { said: ["setup_model"] })).toBeNull();
  });

  it("says the engine's first advice, with its numbers, opening flashcards in place", () => {
    expect(pick(advice([item("vocab_review", { count: 12 }), item("choose_book")]))).toEqual({
      id: "advice:vocab_review",
      key: "vocab_review",
      values: { n: 12 },
      href: "/vocab/review",
      opens: "overlay",
    });
    const kc = { id: "g.x", name_en: "Articles", name_zh: "冠词", cefr: "A2" as const };
    expect(pick(advice([item("grammar_practice", { kc })]), { locale: "zh-CN" })).toMatchObject({
      key: "grammar_practice",
      values: { kc: "冠词" },
      opens: "page",
    });
  });

  it("skips advice about the page the learner is on, and what was said today", () => {
    const a = advice([item("choose_book"), item("placement")]);
    expect(pick(a, { pathname: "/vocab" })?.id).toBe("advice:placement");
    expect(pick(a, { said: ["advice:choose_book"] })?.id).toBe("advice:placement");
  });

  it("then what's left of today's plan, unless on the dashboard where the plan is", () => {
    const left = plan("applied", [true, false, false]);
    expect(pick(advice([]), { plan: left })).toBeNull();
    const pickOn = (p: Plan) => pick(advice([]), { plan: p, pathname: "/learner" });
    expect(pickOn(left)).toMatchObject({
      id: "plan",
      key: "planLeft",
      values: { n: 2 },
    });
    expect(pickOn(plan("proposed", [false]))?.key).toBe("planPending");
    expect(pickOn(plan("applied", [true]))).toBeNull();
    expect(pickOn(plan("declined", [false]))).toBeNull();
    expect(pick(null)).toBeNull();
  });
});

describe("afterReviewNudge", () => {
  it("offers new words once nothing is due", () => {
    expect(afterReviewNudge(advice([item("vocab_learn", { count: 8 })]), [])).toMatchObject({
      id: "after_review",
      values: { n: 8 },
      href: "/vocab/review?mode=new",
      opens: "overlay",
    });
    const stillDue = advice([item("vocab_review", { count: 3 }), item("vocab_learn", { count: 8 })]);
    expect(afterReviewNudge(stillDue, [])).toBeNull();
    expect(afterReviewNudge(advice([item("vocab_learn", { count: 8 })]), ["after_review"])).toBeNull();
  });
});

describe("how often", () => {
  it("at most a few a day, apart unless the learner just did something", () => {
    const now = 1_000_000_000;
    const log = { day: today(), said: ["a"], last: now - MIN_GAP_MS + 1 };
    expect(mayNudge(log, now)).toBe(false);
    expect(mayNudge(log, now, true)).toBe(true);
    expect(mayNudge({ ...log, last: now - MIN_GAP_MS }, now)).toBe(true);
    const full = { ...log, said: Array.from({ length: MAX_PER_DAY }, (_, i) => `n${i}`) };
    expect(mayNudge(full, now, true)).toBe(false);
    // The plan-done cheer doesn't use one up.
    expect(mayNudge({ ...full, said: [...full.said.slice(1), "plan_done"] }, now, true)).toBe(true);
  });

  it("keeps today's log on the device, a new day starting empty", () => {
    noteSaid({ id: "advice:placement", key: "placement" }, 500, "2026-10-14");
    noteSaid(PLAN_DONE_NUDGE, 900, "2026-10-14");
    expect(readLog("2026-10-14")).toEqual({
      day: "2026-10-14",
      said: ["advice:placement", "plan_done"],
      last: 500,
    });
    expect(readLog("2026-10-15")).toEqual({ day: "2026-10-15", said: [], last: 0 });
    window.localStorage.setItem("lingo.tutorPet.nudges", "{oops");
    expect(readLog("2026-10-14").said).toEqual([]);
  });
});
