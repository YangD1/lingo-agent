import { afterEach, describe, expect, it, vi } from "vitest";

import {
  type UsageEstimates,
  callsOf,
  isAiTask,
  loadEstimates,
  resetEstimatesCache,
} from "./ai-usage";

const api = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  api,
}));

const estimates: UsageEstimates = { window: 20, features: [] };

afterEach(() => {
  api.mockReset();
  resetEstimatesCache();
});

describe("loadEstimates", () => {
  it("shares one request between badges until it gets old", async () => {
    api.mockResolvedValue(estimates);
    await Promise.all([loadEstimates(0), loadEstimates(1000)]);
    expect(api).toHaveBeenCalledTimes(1);
    expect(api).toHaveBeenCalledWith("/usage/estimates");

    await loadEstimates(5 * 60 * 1000);
    expect(api).toHaveBeenCalledTimes(2);
  });

  it("does not keep a failed request", async () => {
    api.mockRejectedValueOnce(new Error("offline")).mockResolvedValue(estimates);
    await expect(loadEstimates(0)).rejects.toThrow("offline");
    await expect(loadEstimates(1)).resolves.toBe(estimates);
    expect(api).toHaveBeenCalledTimes(2);
  });
});

it("callsOf is empty for a feature the backend doesn't list", () => {
  expect(callsOf(estimates, "advice")).toEqual([]);
});

it("isAiTask knows the tasks that have a name", () => {
  expect(isAiTask("practice_opening")).toBe(true);
  expect(isAiTask("connection_test")).toBe(false);
});
