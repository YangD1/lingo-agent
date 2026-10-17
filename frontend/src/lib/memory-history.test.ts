import { describe, expect, it } from "vitest";

import { factHistory, withHistory } from "@/lib/memory-history";
import type { Memory } from "@/lib/types";

function fact(id: string, status: Memory["status"] = "active", by: string | null = null): Memory {
  return {
    id,
    kind: "fact",
    content: id,
    source_conversation_id: null,
    source_title: null,
    status,
    superseded_by_id: by,
    created_at: "2026-10-17T08:00:00Z",
    updated_at: "2026-10-17T08:00:00Z",
  };
}

describe("factHistory", () => {
  it("files each old version under the fact it led to, through a chain", () => {
    const memories = [
      fact("chengdu"),
      fact("cat"),
      fact("beijing", "superseded", "chengdu"),
      fact("jazz", "superseded"),
      fact("shanghai", "superseded", "beijing"),
    ];
    const { active, superseded, earlier } = factHistory(memories);
    expect(active.map((m) => m.id)).toEqual(["chengdu", "cat"]);
    expect(superseded.map((m) => m.id)).toEqual(["beijing", "jazz", "shanghai"]);
    expect(earlier.get("chengdu")?.map((m) => m.id)).toEqual(["beijing", "shanghai"]);
    expect(earlier.has("cat")).toBe(false);
  });

  it("leaves dropped facts and broken chains unfiled", () => {
    const { earlier } = factHistory([
      fact("a", "superseded", "b"),
      fact("b", "superseded", "a"), // a cycle never filed, never loops
      fact("c", "superseded", "missing"),
    ]);
    expect(earlier.size).toBe(0);
  });
});

describe("withHistory", () => {
  it("takes the versions a fact replaced, not the others", () => {
    const memories = [
      fact("chengdu"),
      fact("beijing", "superseded", "chengdu"),
      fact("shanghai", "superseded", "beijing"),
      fact("jazz", "superseded"),
    ];
    expect([...withHistory("chengdu", memories)].sort()).toEqual(["beijing", "chengdu", "shanghai"]);
    expect([...withHistory("jazz", memories)]).toEqual(["jazz"]);
  });
});
