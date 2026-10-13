/**
 * The state of a realtime call as the page shows it (ADR 0030, task 62), driven by the
 * relay's JSON events (`backend/app/realtime/relay.py` lists them). Pure, so the
 * protocol is tested without sockets or audio; `use-realtime-call.ts` feeds it.
 */

import type { Activity } from "@/lib/activity";

/** Why a call ended: the relay's reasons, `refused` before it began, or the page's own. */
export type EndReason =
  | "hangup"
  | "vendor_closed"
  | "time_limit"
  | "server_stopping"
  | "browser_closed"
  | "error"
  | "refused"
  | "connection_lost"
  | "microphone_denied"
  | "recording_unsupported";

export type Phase = "idle" | "connecting" | "live" | "wrapping" | "ended";

export type SubtitleLine = {
  kind: "subtitle";
  role: "learner" | "tutor";
  /** null: the learner started talking and their words have not come yet. */
  item_id: string | null;
  text: string;
  final: boolean;
};
export type ToolLine = { kind: "tool"; activity: Activity };
export type CallLine = SubtitleLine | ToolLine;

export type CallState = {
  phase: Phase;
  session_id: string | null;
  conversation_id: string | null;
  input_rate: number;
  output_rate: number;
  limit_seconds: number;
  /** Seconds of the limit used: counted locally, set right by `time_warning`. */
  elapsed: number;
  lines: CallLine[];
  /** The tutor suggested hanging up (Q61c); the learner decides. */
  end_suggested: boolean;
  /** About a minute is left (ADR 0030 §5). */
  warned: boolean;
  /** The last vendor error; the call goes on. */
  error: string | null;
  end_reason: EndReason | null;
  /** With `refused`: why (`realtime_used_up`, `realtime_busy`…). */
  refused_code: string | null;
  /** With `rate_limited`: seconds to wait (ADR 0035). */
  retry_after: number | null;
};

export const initialCall: CallState = {
  phase: "idle",
  session_id: null,
  conversation_id: null,
  input_rate: 0,
  output_rate: 0,
  limit_seconds: 0,
  elapsed: 0,
  lines: [],
  end_suggested: false,
  warned: false,
  error: null,
  end_reason: null,
  refused_code: null,
  retry_after: null,
};

/** A JSON event from the relay. Anything else is ignored. */
export type ServerEvent =
  | {
      type: "ready";
      session_id: string;
      conversation_id: string;
      input_rate: number;
      output_rate: number;
      limit_seconds: number;
    }
  | { type: "subtitle"; role: "learner" | "tutor"; item_id: string; text: string; final: boolean }
  | { type: "speech_started" }
  | { type: "response_done" }
  | ({ type: "tool" } & Activity)
  | { type: "end_suggested" }
  | { type: "time_warning"; remaining_seconds: number }
  | { type: "wrapping_up" }
  | { type: "error"; code: string }
  | { type: "ended"; reason: EndReason; code?: string; retry_after?: number };

export type CallAction =
  | { type: "connect" }
  | { type: "event"; event: ServerEvent }
  | { type: "tick"; seconds: number }
  | { type: "dismiss_end" }
  /** The page ended it: the socket closed without `ended`, or the microphone failed. */
  | { type: "lost"; reason: EndReason };

/** Seconds left of the limit, never below 0. */
export const remainingSeconds = (state: CallState) =>
  Math.max(0, Math.ceil(state.limit_seconds - state.elapsed));

/**
 * A subtitle joins its line: deltas (`final: false`) add to the text, the final one
 * replaces it. The learner's words arrive late, often after the tutor started
 * answering, so `speech_started` holds them a place (`item_id: null`) that their first
 * subtitle fills; a place never filled (noise, nothing transcribed) is dropped when the
 * next one is held.
 */
function subtitle(lines: CallLine[], event: Extract<ServerEvent, { type: "subtitle" }>) {
  const index = lines.findIndex(
    (line) => line.kind === "subtitle" && line.role === event.role && line.item_id === event.item_id,
  );
  if (index >= 0) {
    const line = lines[index] as SubtitleLine;
    if (line.final) return lines;
    const text = event.final ? event.text : line.text + event.text;
    return lines.with(index, { ...line, text, final: event.final });
  }
  const line: SubtitleLine = { kind: "subtitle", ...event };
  if (event.role === "learner") {
    const held = lines.findLastIndex(
      (l) => l.kind === "subtitle" && l.role === "learner" && l.item_id === null,
    );
    if (held >= 0) return dropHeld(lines.with(held, line));
  }
  return [...lines, line];
}

const dropHeld = (lines: CallLine[]) =>
  lines.filter((l) => !(l.kind === "subtitle" && l.item_id === null));

export function callReducer(state: CallState, action: CallAction): CallState {
  // An ended call takes nothing more, until another one starts.
  if (state.phase === "ended" && action.type !== "connect") return state;
  switch (action.type) {
    case "connect":
      return { ...initialCall, phase: "connecting" };
    case "tick":
      return state.phase === "live" || state.phase === "wrapping"
        ? { ...state, elapsed: state.elapsed + action.seconds }
        : state;
    case "dismiss_end":
      return { ...state, end_suggested: false };
    case "lost":
      return { ...state, phase: "ended", end_reason: action.reason, lines: dropHeld(state.lines) };
    case "event":
      return onEvent(state, action.event);
  }
}

function onEvent(state: CallState, event: ServerEvent): CallState {
  switch (event.type) {
    case "ready":
      return {
        ...state,
        phase: "live",
        session_id: event.session_id,
        conversation_id: event.conversation_id,
        input_rate: event.input_rate,
        output_rate: event.output_rate,
        limit_seconds: event.limit_seconds,
        elapsed: 0,
      };
    case "subtitle":
      return { ...state, lines: subtitle(state.lines, event) };
    case "speech_started": {
      // A place still last is still good; one the tutor has talked past was noise.
      const last = state.lines.at(-1);
      if (last?.kind === "subtitle" && last.item_id === null) return state;
      const place: SubtitleLine = { kind: "subtitle", role: "learner", item_id: null, text: "", final: false };
      return { ...state, lines: [...dropHeld(state.lines), place] };
    }
    case "tool": {
      const activity: Activity = {
        turn_id: event.turn_id,
        name: event.name,
        kind: event.kind,
        call_id: event.call_id,
        status: event.status,
        duration_ms: event.duration_ms,
        summary: event.summary,
      };
      return { ...state, lines: [...state.lines, { kind: "tool", activity }] };
    }
    case "end_suggested":
      return { ...state, end_suggested: true };
    case "time_warning":
      return {
        ...state,
        warned: true,
        elapsed: Math.max(state.elapsed, state.limit_seconds - event.remaining_seconds),
      };
    case "wrapping_up":
      return { ...state, phase: "wrapping", elapsed: Math.max(state.elapsed, state.limit_seconds) };
    case "error":
      return { ...state, error: event.code };
    case "ended":
      return {
        ...state,
        phase: "ended",
        end_reason: event.reason,
        refused_code: event.reason === "refused" ? (event.code ?? null) : null,
        retry_after: event.retry_after ?? null,
        end_suggested: false,
        lines: dropHeld(state.lines),
      };
    case "response_done":
      return state;
  }
}

/** Parses a text frame; null for anything that is not a known event. */
export function parseEvent(data: string): ServerEvent | null {
  try {
    const event: unknown = JSON.parse(data);
    if (typeof event !== "object" || event === null) return null;
    const type = (event as { type?: unknown }).type;
    return typeof type === "string" && EVENT_TYPES.has(type) ? (event as ServerEvent) : null;
  } catch {
    return null;
  }
}

const EVENT_TYPES = new Set([
  "ready",
  "subtitle",
  "speech_started",
  "response_done",
  "tool",
  "end_suggested",
  "time_warning",
  "wrapping_up",
  "error",
  "ended",
]);
