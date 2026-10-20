import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  backgroundRunning,
  dismissRunNotice,
  resetRuns,
  runNotice,
  runRunning,
  stopRun,
  trackRun,
  watchRun,
} from "./chat-runs";
import type { ChatEvent } from "./sse";
import { petState, resetPet } from "./tutor-pet";

const TOKEN: ChatEvent = { event: "token", text: "Hi" };
const DONE: ChatEvent = { event: "done", message_id: "m1", turn_id: "u1", usage: {} };

/** A stream that yields `rest` once `gate` opens, or throws an AbortError when aborted. */
function stream(controller: AbortController, rest: ChatEvent[]) {
  let open: () => void = () => {};
  const gate = new Promise<void>((resolve, reject) => {
    open = resolve;
    controller.signal.addEventListener("abort", () =>
      reject(new DOMException("aborted", "AbortError")),
    );
  });
  return {
    open,
    events: (async function* () {
      await gate;
      yield* rest;
    })(),
  };
}

beforeEach(() => {
  resetRuns();
  resetPet();
});

describe("chat runs (ADR 0058)", () => {
  it("writes on with nobody watching, then leaves a notice", async () => {
    const controller = new AbortController();
    const { open, events } = stream(controller, [DONE]);
    const ended = trackRun("c1", "reply", controller, TOKEN, events, null);

    expect(runRunning("c1")).toBe(true);
    expect(backgroundRunning()).toBe(true);
    expect(petState()).toBe("writing");

    open();
    expect(await ended).toBe("done");
    expect(runNotice()).toMatchObject({ conversationId: "c1", kind: "reply", ok: true });
    expect(backgroundRunning()).toBe(false);
    expect(petState()).toBe("happy");

    dismissRunNotice(runNotice()!.at);
    expect(runNotice()).toBeNull();
  });

  it("replays what came to a watcher that comes back, then passes on the rest", async () => {
    const controller = new AbortController();
    const { open, events } = stream(controller, [{ event: "token", text: "!" }, DONE]);
    const ended = trackRun("c1", "opening", controller, TOKEN, events, null);

    const seen: ChatEvent[] = [];
    const end = vi.fn();
    const { found } = watchRun("c1", { event: (e) => seen.push(e), end });
    expect(found).toEqual({ running: true, kind: "opening", events: [TOKEN] });
    expect(petState()).toBe("idle"); // watched: the page shows it

    open();
    await ended;
    expect(seen).toEqual([{ event: "token", text: "!" }, DONE]);
    expect(end).toHaveBeenCalledWith(undefined);
    expect(runNotice()).toBeNull();
    expect(runRunning("c1")).toBe(false);
  });

  it("a reply ending in an error event is a failed one", async () => {
    const controller = new AbortController();
    const failed: ChatEvent = { event: "error", code: "llm_unavailable", message: "down" };
    const { open, events } = stream(controller, [failed]);
    const ended = trackRun("c1", "reply", controller, TOKEN, events, null);
    open();
    expect(await ended).toBe("failed");
    expect(runNotice()).toMatchObject({ ok: false });
  });

  it("stop aborts it, with no notice", async () => {
    const controller = new AbortController();
    const { events } = stream(controller, [DONE]);
    const ended = trackRun("c1", "reply", controller, TOKEN, events, null);

    stopRun("c1");
    expect(await ended).toBe("stopped");
    expect(controller.signal.aborted).toBe(true);
    expect(runNotice()).toBeNull();
    expect(petState()).toBe("idle");
  });

  it("an ended run found later says when it ended, once", async () => {
    const controller = new AbortController();
    const { open, events } = stream(controller, [DONE]);
    const ended = trackRun("c1", "reply", controller, TOKEN, events, null);
    open();
    await ended;

    const watcher = { event: vi.fn(), end: vi.fn() };
    const first = watchRun("c1", watcher).found;
    expect(first).toMatchObject({ running: false });
    expect(runNotice()).toBeNull(); // looked at
    expect(watchRun("c1", watcher).found).toBeNull();
  });
});
