import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Conversation } from "@/lib/types";

import { noteTodayStarted, openingDue, resetToday, useToday } from "./today";

const api = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  api,
}));

const daily = { id: "d1", title: "Today", purpose: "daily" } as Conversation;

function serve(today: Conversation | null, messages: unknown[] = []) {
  api.mockImplementation(async (path: string) => {
    if (path.startsWith("/conversations/today")) return today;
    if (path === `/conversations/${daily.id}/messages`) return messages;
    throw new Error(`unexpected ${path}`);
  });
}

beforeEach(() => {
  api.mockReset();
  resetToday();
});

describe("useToday (ADR 0041)", () => {
  it("is not started before today's conversation exists", async () => {
    serve(null);
    const { result } = renderHook(() => useToday(true));
    expect(result.current).toBeUndefined();
    await waitFor(() => expect(result.current).toEqual({ conversation: null, started: false }));
  });

  it("is not started while today's has nothing said (an opening that failed)", async () => {
    serve(daily, []);
    const { result } = renderHook(() => useToday(true));
    await waitFor(() => expect(result.current).toEqual({ conversation: daily, started: false }));
  });

  it("is started once something was said, and shared with every user of it", async () => {
    serve(daily, [{ role: "assistant" }]);
    const first = renderHook(() => useToday(true));
    await waitFor(() => expect(first.result.current?.started).toBe(true));
    const second = renderHook(() => useToday(true));
    expect(second.result.current?.started).toBe(true);
    expect(api).toHaveBeenCalledTimes(2); // asked once
  });

  it("follows a start noted here", async () => {
    serve(null);
    const { result } = renderHook(() => useToday(true));
    await waitFor(() => expect(result.current?.started).toBe(false));
    act(() => noteTodayStarted(daily));
    expect(result.current).toEqual({ conversation: daily, started: true });
  });

  it("asks nothing while off", () => {
    const { result } = renderHook(() => useToday(false));
    expect(result.current).toBeUndefined();
    expect(api).not.toHaveBeenCalled();
  });

  it("stays unknown when the backend can't be reached", async () => {
    api.mockRejectedValue(new Error("offline"));
    const { result } = renderHook(() => useToday(true));
    await waitFor(() => expect(api).toHaveBeenCalled());
    expect(result.current).toBeUndefined();
  });
});

describe("openingDue", () => {
  const notYet = { conversation: null, started: false };
  it("holds with the switch on, a model, and nothing said today", () => {
    expect(openingDue(true, true, notYet)).toBe(true);
    expect(openingDue(undefined, true, notYet)).toBe(true); // an older backend: on
  });
  it("doesn't otherwise", () => {
    expect(openingDue(false, true, notYet)).toBe(false);
    expect(openingDue(true, false, notYet)).toBe(false);
    expect(openingDue(true, undefined, notYet)).toBe(false); // model not known yet
    expect(openingDue(true, true, undefined)).toBe(false);
    expect(openingDue(true, true, { conversation: null, started: true })).toBe(false);
  });
});
