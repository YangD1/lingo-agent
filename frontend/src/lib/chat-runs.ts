import { useSyncExternalStore } from "react";

import { isAbortError } from "./api";
import type { ChatEvent } from "./sse";
import { petHappy, petHold } from "./tutor-pet";

/**
 * Replies being written, kept for the whole app (ADR 0058 §1): once the backend has taken
 * a turn, its stream is read here to the end, whoever is looking. The conversation on
 * screen watches its run and gets each event; leaving only stops watching, so the reply
 * is still written. Only `stopRun` aborts it. A reply that ends with nobody watching
 * leaves a notice for the desk pet (§3); while one is written that way, the pet writes
 * too (§2).
 */

export type RunKind = "reply" | "opening";
export type RunStatus = "running" | "done" | "failed" | "stopped";

/** Who is looking at the conversation: gets its run's events as they come, then its end. */
export type RunWatcher = {
  event: (event: ChatEvent) => void;
  /** Read to the end; `thrown` is what cut it off (an AbortError when stopped). */
  end: (thrown?: unknown) => void;
};

type Run = {
  conversationId: string;
  kind: RunKind;
  status: RunStatus;
  /** Every event so far: replayed to a watcher that comes back mid-reply. */
  events: ChatEvent[];
  controller: AbortController;
  watcher: RunWatcher | null;
  thrown?: unknown;
  endedAt?: number;
  /** Lets go of the pet's `writing` while nobody watches a running reply. */
  release?: () => void;
};

/** A reply that ended while nobody was looking at its conversation. */
export type RunNotice = { conversationId: string; kind: RunKind; ok: boolean; at: number };

const runs = new Map<string, Run>();
let notice: RunNotice | null = null;
const listeners = new Set<() => void>();

function notify() {
  listeners.forEach((listener) => listener());
}

function holdPet(run: Run) {
  const writing = run.status === "running" && run.watcher === null;
  if (writing && !run.release) run.release = petHold("writing");
  if (!writing && run.release) {
    run.release();
    run.release = undefined;
  }
}

/**
 * Reads `stream` to its end for `conversationId`, from `first`, the event that showed the
 * backend took the turn; `watcher` is the view that sent it. Resolves once it has ended.
 */
export async function trackRun(
  conversationId: string,
  kind: RunKind,
  controller: AbortController,
  first: ChatEvent,
  stream: AsyncGenerator<ChatEvent, void, undefined>,
  watcher: RunWatcher | null,
): Promise<RunStatus> {
  const run: Run = { conversationId, kind, status: "running", events: [], controller, watcher };
  runs.set(conversationId, run);
  if (notice?.conversationId === conversationId) notice = null;
  holdPet(run);
  notify();
  const take = (event: ChatEvent) => {
    run.events.push(event);
    if (event.event === "error") run.status = "failed";
    run.watcher?.event(event);
  };
  try {
    take(first);
    for (let step = await stream.next(); !step.done; step = await stream.next()) take(step.value);
    if (run.status === "running") run.status = "done";
  } catch (e) {
    run.thrown = e;
    run.status = isAbortError(e) ? "stopped" : "failed";
  }
  run.endedAt = Date.now();
  holdPet(run);
  const seen = run.watcher;
  if (seen) {
    runs.delete(conversationId);
    seen.end(run.thrown);
  } else if (run.status !== "stopped") {
    notice = { conversationId, kind, ok: run.status === "done", at: run.endedAt };
    petHappy();
  }
  notify();
  return run.status;
}

/** What a view coming to `conversationId` finds: a reply still being written, or one that
 * ended while it was away (its history may be older than that). */
export type RunFound =
  | { running: true; kind: RunKind; events: ChatEvent[] }
  | { running: false; endedAt: number }
  | null;

/**
 * Starts watching `conversationId`'s run, if any. A running one returns its events so far,
 * for the view to replay before the ones still to come. Returns how to stop watching.
 */
export function watchRun(
  conversationId: string,
  watcher: RunWatcher,
): { found: RunFound; unwatch: () => void } {
  const run = runs.get(conversationId);
  if (notice?.conversationId === conversationId) {
    notice = null; // looked at now
    notify();
  }
  if (!run) return { found: null, unwatch: () => {} };
  if (run.status !== "running") {
    runs.delete(conversationId); // seen: nothing more to tell
    return { found: { running: false, endedAt: run.endedAt ?? 0 }, unwatch: () => {} };
  }
  run.watcher = watcher;
  holdPet(run);
  return {
    found: { running: true, kind: run.kind, events: [...run.events] },
    unwatch: () => unwatchRun(conversationId, watcher),
  };
}

/** Stops `watcher` watching: the reply goes on being written. */
export function unwatchRun(conversationId: string, watcher: RunWatcher) {
  const run = runs.get(conversationId);
  if (run?.watcher !== watcher) return;
  run.watcher = null;
  holdPet(run);
  notify();
}

/** The stop button: the reply is cut off here and on the backend. */
export function stopRun(conversationId: string) {
  runs.get(conversationId)?.controller.abort();
}

/** Whether a reply is being written in `conversationId`. */
export function runRunning(conversationId: string): boolean {
  return runs.get(conversationId)?.status === "running";
}

/** The latest reply that ended unwatched, until it is looked at or dismissed. */
export function runNotice(): RunNotice | null {
  return notice;
}

export function dismissRunNotice(at: number) {
  if (notice?.at !== at) return;
  notice = null;
  notify();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** The latest notice, kept up to date. */
export function useRunNotice(): RunNotice | null {
  return useSyncExternalStore(subscribe, runNotice, () => null);
}

/** Whether a reply is being written with nobody watching (the collapsed pet's ring). */
export function backgroundRunning(): boolean {
  for (const run of runs.values()) {
    if (run.status === "running" && run.watcher === null) return true;
  }
  return false;
}

export function useBackgroundRunning(): boolean {
  return useSyncExternalStore(subscribe, backgroundRunning, () => false);
}

/** Back to nothing (tests). */
export function resetRuns() {
  for (const run of runs.values()) run.release?.();
  runs.clear();
  notice = null;
}
