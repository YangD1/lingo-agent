import { describe, expect, it } from "vitest";

import { isOff, joinLink, left } from "./org";

describe("left", () => {
  it("is what's left under the tighter cap", () => {
    expect(left({ daily: 1000, monthly: 5000 }, { day: 200, month: 4500 })).toBe(500);
    expect(left({ daily: 1000, monthly: 5000 }, { day: 900, month: 1000 })).toBe(100);
  });

  it("never goes below 0: the last call may run past a cap (ADR 0031 §6)", () => {
    expect(left({ daily: 100, monthly: null }, { day: 130, month: 130 })).toBe(0);
  });

  it("is null with no cap", () => {
    expect(left({ daily: null, monthly: null }, { day: 9999, month: 9999 })).toBeNull();
  });
});

describe("isOff", () => {
  it("is a 0 cap on either period", () => {
    expect(isOff({ daily: 0, monthly: null })).toBe(true);
    expect(isOff({ daily: null, monthly: 0 })).toBe(true);
    expect(isOff({ daily: null, monthly: null })).toBe(false);
  });
});

describe("joinLink", () => {
  it("puts the code in the /join page's query", () => {
    expect(joinLink("ab c/d", "https://lingo.example")).toBe("https://lingo.example/join?code=ab%20c%2Fd");
  });
});
