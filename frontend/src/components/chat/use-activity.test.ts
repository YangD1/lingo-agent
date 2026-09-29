import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Activity, ConversationActivity } from "@/lib/activity";

import { POLL_DELAYS, useActivity } from "./use-activity";

const fetchActivity = vi.hoisted(() => vi.fn());
vi.mock("@/lib/activity", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/activity")>()),
  fetchActivity,
}));

const tagged: Activity = {
  turn_id: "u1",
  name: "grammar_tagging",
  kind: "background",
  call_id: "",
  status: "ok",
  duration_ms: 5,
  summary: { mistakes: [], used_correctly: [] },
};

const body = (pending: boolean, activities: Activity[] = []): ConversationActivity => ({
  activities,
  memories: {},
  kcs: {},
  pending,
});

beforeEach(() => {
  vi.useFakeTimers();
  fetchActivity.mockReset();
});
afterEach(() => vi.useRealTimers());

async function advance(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

describe("useActivity", () => {
  it("loads the conversation's activity, then polls a finished turn until nothing is pending", async () => {
    fetchActivity.mockResolvedValueOnce(body(false));
    const { result } = renderHook(() => useActivity("c1", true));
    await advance(0);
    expect(fetchActivity).toHaveBeenCalledWith("c1");

    fetchActivity.mockResolvedValueOnce(body(true)).mockResolvedValueOnce(body(false, [tagged]));
    act(() => result.current.turnFinished("c1", "u1"));
    expect(result.current.waiting.has("u1")).toBe(true);

    await advance(POLL_DELAYS[0]);
    expect(fetchActivity).toHaveBeenLastCalledWith("c1", ["u1"]);
    expect(result.current.waiting.has("u1")).toBe(true);
    await advance(POLL_DELAYS[1] - POLL_DELAYS[0]);

    expect(result.current.byTurn.u1).toEqual([tagged]);
    expect(result.current.waiting.has("u1")).toBe(false);
    await advance(60_000);
    expect(fetchActivity).toHaveBeenCalledTimes(3); // no more polls
  });

  it("gives up after the last delay", async () => {
    fetchActivity.mockResolvedValue(body(true));
    const { result } = renderHook(() => useActivity("c1", true));
    act(() => result.current.turnFinished("c1", "u1"));

    await advance(POLL_DELAYS.at(-1)! + 1000);

    expect(fetchActivity).toHaveBeenCalledTimes(1 + POLL_DELAYS.length);
    expect(result.current.waiting.has("u1")).toBe(false);
  });

  it("fetches nothing when the learner hid it", async () => {
    const { result } = renderHook(() => useActivity("c1", false));
    act(() => result.current.turnFinished("c1", "u1"));
    await advance(60_000);
    expect(fetchActivity).not.toHaveBeenCalled();
  });

  it("drops another conversation's results after a switch", async () => {
    fetchActivity.mockResolvedValue(body(false, [tagged]));
    const { result, rerender } = renderHook(({ id }) => useActivity(id, true), {
      initialProps: { id: "c1" },
    });
    await advance(0);
    expect(result.current.byTurn.u1).toHaveLength(1);

    fetchActivity.mockResolvedValue(body(false));
    rerender({ id: "c2" });
    await advance(0);

    expect(result.current.byTurn).toEqual({});
  });
});
