import { describe, expect, it } from "vitest";

import { groupOf } from "./conversation-list";

describe("groupOf", () => {
  const now = new Date(2026, 9, 1, 15, 0); // Thursday 1 October 2026, 15:00 local

  it("puts conversations from today under today", () => {
    expect(groupOf(new Date(2026, 9, 1, 0, 5).toISOString(), now)).toBe("today");
  });

  it("puts the six days before today under this week", () => {
    expect(groupOf(new Date(2026, 8, 30, 23, 59).toISOString(), now)).toBe("week");
    expect(groupOf(new Date(2026, 8, 25, 0, 0).toISOString(), now)).toBe("week");
  });

  it("puts anything older under earlier", () => {
    expect(groupOf(new Date(2026, 8, 24, 23, 59).toISOString(), now)).toBe("earlier");
  });
});
