import { describe, expect, it } from "vitest";

import { MAX_ELAPSED_MS, elapsedMs } from "./elapsed";

describe("elapsedMs", () => {
  it("rounds and keeps times up to an hour", () => {
    expect(elapsedMs(1234.6)).toBe(1235);
    expect(elapsedMs(-3)).toBe(0);
    expect(elapsedMs(MAX_ELAPSED_MS)).toBe(MAX_ELAPSED_MS);
  });

  it("drops a time longer than an hour, so the answer is not refused", () => {
    expect(elapsedMs(MAX_ELAPSED_MS + 1)).toBeUndefined();
    expect(elapsedMs(5 * 3_600_000)).toBeUndefined();
    expect(elapsedMs(Number.NaN)).toBeUndefined();
    expect(elapsedMs(undefined)).toBeUndefined();
  });
});
