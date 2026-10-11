import { describe, expect, it } from "vitest";

import {
  type CallAction,
  callReducer,
  type CallState,
  initialCall,
  parseEvent,
  remainingSeconds,
  type ServerEvent,
} from "./realtime-call";

const READY: ServerEvent = {
  type: "ready",
  session_id: "s1",
  conversation_id: "c1",
  input_rate: 24000,
  output_rate: 24000,
  limit_seconds: 900,
};

function run(...steps: (ServerEvent | CallAction)[]): CallState {
  return steps.reduce<CallState>(
    (state, step) =>
      callReducer(
        state,
        "event" in step || ["connect", "tick", "dismiss_end", "lost"].includes(step.type)
          ? (step as CallAction)
          : { type: "event", event: step as ServerEvent },
      ),
    initialCall,
  );
}

const sub = (role: "learner" | "tutor", item_id: string, text: string, final = false) =>
  ({ type: "subtitle", role, item_id, text, final }) as const;

const texts = (state: CallState) =>
  state.lines.map((l) => (l.kind === "subtitle" ? `${l.role}:${l.text}${l.final ? "" : "…"}` : `tool:${l.activity.name}`));

describe("callReducer", () => {
  it("goes live on ready with the call's ids, rates and limit", () => {
    const state = run({ type: "connect" }, READY);
    expect(state).toMatchObject({
      phase: "live",
      session_id: "s1",
      conversation_id: "c1",
      input_rate: 24000,
      limit_seconds: 900,
    });
    expect(remainingSeconds(state)).toBe(900);
  });

  it("adds deltas to a line and replaces them with the final text", () => {
    const state = run(
      { type: "connect" },
      READY,
      sub("tutor", "t1", "Hi"),
      sub("tutor", "t1", " there"),
      sub("tutor", "t1", "Hi there!", true),
      sub("tutor", "t1", " late delta"),
    );
    expect(texts(state)).toEqual(["tutor:Hi there!"]);
  });

  it("puts the learner's late words where they started talking", () => {
    const state = run(
      { type: "connect" },
      READY,
      sub("tutor", "t1", "How are you?", true),
      { type: "speech_started" },
      sub("tutor", "t2", "Great"),
      sub("learner", "l1", "I'm fine", true),
    );
    expect(texts(state)).toEqual(["tutor:How are you?", "learner:I'm fine", "tutor:Great…"]);
  });

  it("drops a held place nobody filled", () => {
    const state = run(
      { type: "connect" },
      READY,
      { type: "speech_started" }, // a cough: no words
      sub("tutor", "t1", "Sorry?", true),
      { type: "speech_started" },
      sub("learner", "l1", "Nothing", true),
    );
    expect(texts(state)).toEqual(["tutor:Sorry?", "learner:Nothing"]);
  });

  it("holds one place at a time", () => {
    const state = run({ type: "connect" }, READY, { type: "speech_started" }, { type: "speech_started" });
    expect(state.lines).toHaveLength(1);
  });

  it("shows tools in the flow and the suggestion to hang up", () => {
    const state = run(
      { type: "connect" },
      READY,
      {
        type: "tool",
        turn_id: "m1",
        name: "add_to_vocab",
        kind: "tool",
        call_id: "c1",
        status: "ok",
        duration_ms: 12,
        summary: { added: [{ word_id: 5, word: "sustainable" }], existing: [] },
      },
      { type: "end_suggested" },
    );
    expect(state.lines[0]).toEqual({
      kind: "tool",
      activity: {
        turn_id: "m1",
        name: "add_to_vocab",
        kind: "tool",
        call_id: "c1",
        status: "ok",
        duration_ms: 12,
        summary: { added: [{ word_id: 5, word: "sustainable" }], existing: [] },
      },
    });
    expect(state.end_suggested).toBe(true);
    expect(callReducer(state, { type: "dismiss_end" }).end_suggested).toBe(false);
  });

  it("counts down locally and takes the warning's remaining time", () => {
    let state = run({ type: "connect" }, { ...READY, limit_seconds: 120 }, { type: "tick", seconds: 1 });
    expect(remainingSeconds(state)).toBe(119);
    state = callReducer(state, { type: "event", event: { type: "time_warning", remaining_seconds: 60 } });
    expect(state.warned).toBe(true);
    expect(remainingSeconds(state)).toBe(60);
  });

  it("does not tick before ready", () => {
    expect(run({ type: "connect" }, { type: "tick", seconds: 5 }).elapsed).toBe(0);
  });

  it("wraps up at the limit", () => {
    const state = run({ type: "connect" }, { ...READY, limit_seconds: 60 }, { type: "wrapping_up" });
    expect(state.phase).toBe("wrapping");
    expect(remainingSeconds(state)).toBe(0);
  });

  it("keeps the call on a vendor error", () => {
    const state = run({ type: "connect" }, READY, { type: "error", code: "rate_limit_exceeded" });
    expect(state).toMatchObject({ phase: "live", error: "rate_limit_exceeded" });
  });

  it("ends with the reason and freezes", () => {
    const state = run(
      { type: "connect" },
      READY,
      { type: "speech_started" },
      { type: "ended", reason: "time_limit" },
      sub("tutor", "t9", "after the end", true),
    );
    expect(state).toMatchObject({ phase: "ended", end_reason: "time_limit", refused_code: null });
    expect(state.lines).toEqual([]);
  });

  it("keeps why a call was refused", () => {
    const state = run({ type: "connect" }, { type: "ended", reason: "refused", code: "realtime_used_up" });
    expect(state).toMatchObject({ end_reason: "refused", refused_code: "realtime_used_up" });
  });

  it("ends when the page loses the call", () => {
    expect(run({ type: "connect" }, { type: "lost", reason: "connection_lost" })).toMatchObject({
      phase: "ended",
      end_reason: "connection_lost",
    });
  });

  it("starts afresh when another call connects", () => {
    const ended = run({ type: "connect" }, READY, sub("tutor", "t1", "Bye", true), {
      type: "ended",
      reason: "hangup",
    });
    expect(callReducer(ended, { type: "connect" })).toEqual({ ...initialCall, phase: "connecting" });
  });
});

describe("parseEvent", () => {
  it("reads known events", () => {
    expect(parseEvent('{"type":"response_done"}')).toEqual({ type: "response_done" });
  });

  it("ignores anything else", () => {
    expect(parseEvent("not json")).toBeNull();
    expect(parseEvent("[1]")).toBeNull();
    expect(parseEvent('{"type":"session.update"}')).toBeNull();
    expect(parseEvent("null")).toBeNull();
  });
});
