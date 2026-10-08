import { describe, expect, it } from "vitest";

import { type KCStatus, learnedChecks } from "@/lib/learner";

const GATE = { min_formats: 3, min_span_hours: 20, clean_days: 14 };
const NOW = new Date("2026-10-02T12:00:00Z");

const kc = (overrides: Partial<KCStatus>): KCStatus => ({
  kc_id: "g.x",
  name_en: "X",
  name_zh: "X",
  cefr: "A2",
  p_mastery: 0.5,
  state: "learning",
  observations: 3,
  recog_correct: 1,
  produce_correct: 1,
  mistakes: 1,
  last_evidence_at: null,
  formats_passed: [],
  correct_span_hours: 0,
  last_mistake_at: null,
  mastered_at: null,
  due: null,
  prerequisites: [],
  confusables: [],
  ...overrides,
});

const met = (k: KCStatus) =>
  Object.fromEntries(learnedChecks(k, GATE, 0.95, NOW).map((c) => [c.key, c.met]));

describe("learnedChecks", () => {
  it("checks each condition on its own", () => {
    expect(met(kc({}))).toEqual({ mastery: false, formats: false, span: false, clean: true });
    expect(
      met(
        kc({
          p_mastery: 0.95,
          formats_passed: ["choice4", "cloze", "translate"],
          correct_span_hours: 20,
        }),
      ),
    ).toEqual({ mastery: true, formats: true, span: true, clean: true });
  });

  it("counts whole days since the latest mistake", () => {
    const recent = learnedChecks(
      kc({ last_mistake_at: "2026-09-20T13:00:00Z" }),
      GATE,
      0.95,
      NOW,
    ).find((c) => c.key === "clean");
    expect(recent).toEqual({ key: "clean", met: false, value: 11, target: 14 });
    const old = learnedChecks(kc({ last_mistake_at: "2026-09-18T12:00:00Z" }), GATE, 0.95, NOW);
    expect(old.find((c) => c.key === "clean")?.met).toBe(true);
  });

  it("rounds mastery to whole percent and floors the hours", () => {
    const [mastery, , span] = learnedChecks(
      kc({ p_mastery: 0.876, correct_span_hours: 19.9 }),
      GATE,
      0.95,
      NOW,
    );
    expect(mastery).toMatchObject({ value: 88, target: 95 });
    expect(span).toMatchObject({ value: 19, met: false });
  });
});
