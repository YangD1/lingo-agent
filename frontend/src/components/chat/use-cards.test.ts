import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { TutorCard } from "@/lib/cards";

import { useCards } from "./use-cards";

const api = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  api,
}));

const card = (id: string, turn: string, overrides: Partial<TutorCard> = {}): TutorCard => ({
  id,
  turn_id: turn,
  kind: "link",
  params: { kind: "vocab_review" },
  status: "info",
  display: {},
  created_at: null,
  decided_at: null,
  undone_at: null,
  ...overrides,
});

beforeEach(() => api.mockReset());

describe("useCards", () => {
  it("loads, adds streamed cards and applies decisions", async () => {
    const listed = card("k1", "u1", { live: { reviews_due: 3, new_left: 0 } });
    api.mockResolvedValueOnce({ cards: [listed] });
    const { result } = renderHook(() => useCards("c1"));
    await waitFor(() => expect(result.current.byTurn.u1).toHaveLength(1));
    expect(api.mock.calls[0][0]).toMatch(/^\/conversations\/c1\/cards/);

    // Streamed again without numbers: the listed ones stay.
    act(() => result.current.add(card("k1", "u1")));
    act(() => result.current.add(card("k2", "u2", { kind: "word_book", status: "proposed" })));
    expect(result.current.byTurn.u1[0].live).toEqual({ reviews_due: 3, new_left: 0 });
    expect(result.current.byTurn.u2).toHaveLength(1);

    api.mockResolvedValueOnce(card("k2", "u2", { kind: "word_book", status: "applied" }));
    await act(() => result.current.decide(result.current.byTurn.u2[0], "apply"));
    // The browser's time zone tells a daily plan card which day it is (jsdom: UTC).
    expect(api).toHaveBeenLastCalledWith("/cards/k2/apply", {
      method: "POST",
      json: { tz: expect.any(String) },
    });
    expect(result.current.byTurn.u2[0].status).toBe("applied");
  });

  it("starts empty on another conversation", async () => {
    api.mockResolvedValueOnce({ cards: [card("k1", "u1")] }).mockResolvedValueOnce({ cards: [] });
    const { result, rerender } = renderHook(({ id }) => useCards(id), {
      initialProps: { id: "c1" as string | null },
    });
    await waitFor(() => expect(result.current.byTurn.u1).toHaveLength(1));
    rerender({ id: "c2" });
    expect(result.current.byTurn).toEqual({});
  });
});
