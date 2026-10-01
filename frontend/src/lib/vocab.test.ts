import { describe, expect, it } from "vitest";

import { formatInterval } from "./vocab";

describe("formatInterval", () => {
  it("rounds to the unit a learner thinks in", () => {
    expect(formatInterval(0, "en")).toBe("<1 min");
    expect(formatInterval(330, "en")).toBe("6 min");
    expect(formatInterval(3 * 3600 + 100, "en")).toBe("3 hr");
    expect(formatInterval(4 * 86_400, "en")).toBe("4 days");
    expect(formatInterval(65 * 86_400, "en")).toBe("2 mths");
    expect(formatInterval(550 * 86_400, "en")).toBe("1.5 yrs");
  });

  it("speaks the interface language", () => {
    expect(formatInterval(600, "zh-CN")).toBe("10分钟");
    expect(formatInterval(86_400, "zh-CN")).toBe("1天");
  });
});
