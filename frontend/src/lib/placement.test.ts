// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";

import { answerPlacement, dismissPlacementReminder, type Placement } from "./placement";

const placement = (status: Placement["status"]): Placement => ({
  id: "p1",
  status,
  stage: "vocab",
  answered: 0,
  question: null,
  result: null,
  created_at: "2026-09-30T00:00:00Z",
  finished_at: null,
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("answerPlacement", () => {
  it("sends the question id with the answer", async () => {
    const fetch = vi.fn(async () => Response.json(placement("in_progress")));
    vi.stubGlobal("fetch", fetch);

    await answerPlacement("p1", "grammar-3", { choice: 2 });

    const [url, init] = fetch.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/api/placement/p1/answer");
    expect(JSON.parse(init.body as string)).toEqual({ question_id: "grammar-3", choice: 2 });
  });
});

describe("dismissPlacementReminder", () => {
  it("sends the reminder's key back", async () => {
    const fetch = vi.fn(async () => new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetch);

    await dismissPlacementReminder("progress:p1");

    const [url, init] = fetch.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/api/placement/reminder/dismiss");
    expect(JSON.parse(init.body as string)).toEqual({ key: "progress:p1" });
  });
});
