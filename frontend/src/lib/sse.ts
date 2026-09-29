import { EventSourceParserStream } from "eventsource-parser/stream";

import type { Activity } from "./activity";
import { apiFetch } from "./api";

/** The chat SSE protocol (ADR 0003 §2). */
export type ChatEvent =
  | { event: "token"; text: string }
  /** A step of this turn as it happens (ADR 0013 §3). */
  | ({ event: "activity" } & Omit<Activity, "created_at">)
  | {
      event: "done";
      message_id: string | null;
      /** The learner message's id: background activity of this turn is filed under it. */
      turn_id: string | null;
      usage: { input_tokens?: number; output_tokens?: number };
    }
  | { event: "error"; code: string; message: string };

const KNOWN_EVENTS = new Set(["token", "activity", "done", "error"]);

/**
 * Send a message and yield the reply's events. POST + fetch because EventSource can't
 * send a body. Errors before the stream starts (404, 409 no_llm_configured /
 * conversation_busy) throw ApiError; aborting `signal` stops generation server-side
 * too and rejects with an AbortError.
 *
 * Always ends with exactly one `done` or `error`: a stream that closes without either
 * (connection dropped) yields a synthetic `error` with code `stream_interrupted`.
 */
export async function* streamChat(
  conversationId: string,
  content: string,
  { signal, attachmentIds = [] }: { signal?: AbortSignal; attachmentIds?: string[] } = {},
): AsyncGenerator<ChatEvent, void, undefined> {
  const response = await apiFetch(`/conversations/${conversationId}/messages`, {
    method: "POST",
    headers: { "content-type": "application/json", accept: "text/event-stream" },
    body: JSON.stringify({ content, attachment_ids: attachmentIds }),
    signal,
  });
  if (!response.body) throw new Error("response has no body");

  const events = response.body
    .pipeThrough(new TextDecoderStream())
    .pipeThrough(new EventSourceParserStream());
  const reader = events.getReader();
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      if (!KNOWN_EVENTS.has(value.event ?? "")) continue; // forward-compatible
      const event = { event: value.event, ...JSON.parse(value.data) } as ChatEvent;
      yield event;
      if (event.event === "done" || event.event === "error") return;
    }
  } finally {
    reader.releaseLock();
    // Stop reading if the consumer bailed out early (e.g. component unmounted).
    await events.cancel().catch(() => {});
  }
  yield { event: "error", code: "stream_interrupted", message: "the reply stream ended early" };
}
