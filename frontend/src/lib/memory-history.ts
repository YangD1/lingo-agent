import type { Memory } from "@/lib/types";

/**
 * Facts the tutor rewrote or dropped are kept as `superseded` (ADR 0053 §4). The page
 * lists the active ones, each with the versions it replaced, and the superseded ones
 * below, newest first as the backend sends them.
 */
export type FactHistory = {
  active: Memory[];
  superseded: Memory[];
  /** Active fact id -> the older versions that led to it, newest first. */
  earlier: Map<string, Memory[]>;
};

export function factHistory(memories: Memory[]): FactHistory {
  const byId = new Map(memories.map((m) => [m.id, m]));
  const active = memories.filter((m) => m.status === "active");
  const superseded = memories.filter((m) => m.status === "superseded");
  const earlier = new Map<string, Memory[]>();
  for (const old of superseded) {
    const current = currentVersion(old, byId);
    if (current) earlier.set(current.id, [...(earlier.get(current.id) ?? []), old]);
  }
  return { active, superseded, earlier };
}

/** The active fact `old` was eventually replaced by; undefined when it was dropped. */
export function currentVersion(old: Memory, byId: Map<string, Memory>): Memory | undefined {
  const seen = new Set<string>();
  let next = old.superseded_by_id ? byId.get(old.superseded_by_id) : undefined;
  while (next && next.status === "superseded" && !seen.has(next.id)) {
    seen.add(next.id);
    next = next.superseded_by_id ? byId.get(next.superseded_by_id) : undefined;
  }
  return next?.status === "active" ? next : undefined;
}

/** Ids the backend deletes with `id`: it and every version it replaced. */
export function withHistory(id: string, memories: Memory[]): Set<string> {
  const ids = new Set([id]);
  let grew = true;
  while (grew) {
    grew = false;
    for (const m of memories) {
      if (m.superseded_by_id && ids.has(m.superseded_by_id) && !ids.has(m.id)) {
        ids.add(m.id);
        grew = true;
      }
    }
  }
  return ids;
}
