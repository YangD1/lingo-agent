import { afterEach, describe, expect, it, vi } from "vitest";

import { type Activity, digest, fetchActivity, mergeActivities } from "./activity";

const step = (name: string, summary: Record<string, unknown>, extra: Partial<Activity> = {}) =>
  ({
    turn_id: "u1",
    name,
    kind: name === "load_context" ? "step" : "background",
    call_id: "",
    status: "ok",
    duration_ms: 1,
    summary,
    ...extra,
  }) as Activity;

afterEach(() => vi.unstubAllGlobals());

describe("digest", () => {
  it("adds up what the tutor read, saved and marked", () => {
    const d = digest([
      step("load_context", { facts: ["f1", "f2"], episodes: ["e1"], profile_items: 3 }),
      step("reflect_memory", { added: ["f3"], updated: ["f1"], deleted: 1, profile_fields: ["goal"] }),
      step("grammar_tagging", {
        mistakes: [{ kc_id: "g.x", error_type: "omission", severity: "low", original: "a" }],
        used_correctly: ["g.y", "g.z"],
      }),
      step("summarize", { episode_id: "e2" }),
    ]);
    expect(d).toMatchObject({
      memoriesRead: 3,
      memoriesSaved: 2,
      memoriesDeleted: 1,
      profileUpdated: true,
      mistakes: 1,
      usedCorrectly: 2,
      summaryUpdated: true,
      failed: [],
      skipped: [],
    });
  });

  it("counts nothing from failed or skipped steps", () => {
    const d = digest([
      step("reflect_memory", {}, { status: "failed" }),
      step("grammar_tagging", {}, { status: "skipped" }),
    ]);
    expect(d).toMatchObject({ memoriesSaved: 0, failed: ["reflect_memory"], skipped: ["grammar_tagging"] });
  });
});

describe("mergeActivities", () => {
  it("replaces a step recorded again and keeps the others", () => {
    const merged = mergeActivities(
      [step("load_context", {}), step("reflect_memory", {}, { status: "failed" })],
      [step("reflect_memory", { deleted: 1 })],
    );
    expect(merged.map((a) => [a.name, a.status])).toEqual([
      ["load_context", "ok"],
      ["reflect_memory", "ok"],
    ]);
  });
});

describe("fetchActivity", () => {
  it("asks for the given turns only", async () => {
    const fetch = vi.fn<typeof globalThis.fetch>(
      async () => new Response('{"activities": [], "memories": {}, "kcs": {}, "pending": false}'),
    );
    vi.stubGlobal("fetch", fetch);
    await fetchActivity("c1", ["u1", "u2"]);
    await fetchActivity("c1");
    expect(fetch.mock.calls.map(([url]) => url)).toEqual([
      "/api/conversations/c1/activity?turn=u1&turn=u2",
      "/api/conversations/c1/activity",
    ]);
  });
});
