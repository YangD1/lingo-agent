import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Activity, ConversationActivity } from "@/lib/activity";
import { ApiError } from "@/lib/api";

import { POLL_DELAYS, useActivity } from "./use-activity";

const fetchActivity = vi.hoisted(() => vi.fn());
const removeMine = vi.hoisted(() => vi.fn());
vi.mock("@/lib/vocab", () => ({ removeMine }));
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

const body = (
  pending: boolean,
  activities: Activity[] = [],
  words_on_list: number[] = [],
): ConversationActivity => ({
  activities,
  memories: {},
  kcs: {},
  words_on_list,
  pending,
});

const collected: Activity = {
  ...tagged,
  name: "vocab_collect",
  summary: {
    added: [
      { word_id: 7, word: "go" },
      { word_id: 8, word: "reluctant" },
    ],
    existing: [],
  },
};

beforeEach(() => {
  vi.useFakeTimers();
  fetchActivity.mockReset();
  removeMine.mockReset();
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

  it("knows which collected words are still on the list, and removes them", async () => {
    fetchActivity.mockResolvedValueOnce(body(false, [collected], [7]));
    const { result } = renderHook(() => useActivity("c1", true));
    await advance(0);
    expect(result.current.wordsOnList).toEqual({ 7: true, 8: false });

    removeMine.mockResolvedValueOnce(undefined);
    await act(() => result.current.removeWord(7));
    expect(removeMine).toHaveBeenCalledWith(7);
    expect(result.current.wordsOnList[7]).toBe(false);
  });

  it("treats a word already gone as removed, and passes other errors on", async () => {
    fetchActivity.mockResolvedValueOnce(body(false, [collected], [7, 8]));
    const { result } = renderHook(() => useActivity("c1", true));
    await advance(0);

    removeMine.mockRejectedValueOnce(new ApiError(404, "word_not_found", "gone"));
    await act(() => result.current.removeWord(7));
    expect(result.current.wordsOnList[7]).toBe(false);

    removeMine.mockRejectedValueOnce(new ApiError(0, "network_error", "offline"));
    await expect(act(() => result.current.removeWord(8))).rejects.toThrow("offline");
    expect(result.current.wordsOnList[8]).toBe(true);
  });
});
