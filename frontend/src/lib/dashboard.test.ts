import { describe, expect, it } from "vitest";

import { type Day, hasGrammar, intensity, weeks } from "@/lib/dashboard";

const day = (date: string, reviews = 0, turns = 0): Day => ({ date, reviews, turns });

describe("weeks", () => {
  it("lays days out Monday first, padding both ends", () => {
    // 2026-09-30 is a Wednesday.
    const days = [day("2026-09-30"), day("2026-10-01"), day("2026-10-02")];
    const result = weeks(days);
    expect(result).toHaveLength(1);
    expect(result[0].map((d) => d?.date ?? null)).toEqual([
      null,
      null,
      "2026-09-30",
      "2026-10-01",
      "2026-10-02",
      null,
      null,
    ]);
  });

  it("starts a new column each Monday", () => {
    const days = [day("2026-10-04"), day("2026-10-05")]; // Sunday, Monday
    expect(weeks(days).map((w) => w.filter(Boolean).map((d) => d!.date))).toEqual([
      ["2026-10-04"],
      ["2026-10-05"],
    ]);
    expect(weeks([])).toEqual([]);
  });
});

describe("intensity", () => {
  it("is 0 for no activity, then quarters of the busiest day", () => {
    expect(intensity(day("d"), 0)).toBe(0);
    expect(intensity(day("d"), 8)).toBe(0);
    expect(intensity(day("d", 1), 8)).toBe(1);
    expect(intensity(day("d", 2, 1), 8)).toBe(2);
    expect(intensity(day("d", 5, 1), 8)).toBe(3);
    expect(intensity(day("d", 8), 8)).toBe(4);
  });
});

describe("hasGrammar", () => {
  const level = (unseen: number) => ({ total: 3, mastered: 0, learning: 0, weak: 3 - unseen, unseen });
  it("is true once any level has a point met", () => {
    const none = { A1: level(3), A2: level(3), B1: level(3), B2: level(3), C1: level(3), C2: level(3) };
    expect(hasGrammar(none)).toBe(false);
    expect(hasGrammar({ ...none, B1: level(2) })).toBe(true);
  });
});
