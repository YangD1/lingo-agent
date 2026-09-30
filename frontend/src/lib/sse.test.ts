// @vitest-environment node
import { createServer } from "node:http";
import type { AddressInfo } from "node:net";

import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "./api";
import { type ChatEvent, streamChat } from "./sse";

/** An SSE response delivered in the given raw chunks (split anywhere, like TCP does). */
function sseResponse(chunks: string[]): Response {
  const encoder = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
  return new Response(body, { headers: { "content-type": "text/event-stream" } });
}

function mockFetch(response: Response) {
  const fn = vi.fn<typeof fetch>(async () => response);
  vi.stubGlobal("fetch", fn);
  return fn;
}

async function collect(stream: AsyncIterable<ChatEvent>): Promise<ChatEvent[]> {
  const out: ChatEvent[] = [];
  for await (const event of stream) out.push(event);
  return out;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("streamChat", () => {
  it("parses tokens split across chunks, ignoring keepalives and unknown events", async () => {
    const fetch = mockFetch(
      sseResponse([
        'event: token\ndata: {"text": "Hel',
        'lo"}\n\n: ping\n\nevent: token\ndata: {"text": "!"}\n\n',
        'event: future_thing\ndata: {}\n\n',
        'event: done\ndata: {"message_id": "m1", "usage": {"input_tokens": 3, "output_tokens": 2}}\n\n',
      ]),
    );

    const events = await collect(streamChat("c1", "hi", { attachmentIds: ["a1"] }));

    expect(events).toEqual([
      { event: "token", text: "Hello" },
      { event: "token", text: "!" },
      { event: "done", message_id: "m1", usage: { input_tokens: 3, output_tokens: 2 } },
    ]);
    const [url, init] = fetch.mock.calls[0];
    expect(url).toBe("/api/conversations/c1/messages");
    expect(init?.method).toBe("POST");
    expect(init?.body).toBe('{"content":"hi","attachment_ids":["a1"]}');
  });

  it("passes activity steps through and keeps reading after them", async () => {
    mockFetch(
      sseResponse([
        'event: activity\ndata: {"turn_id": "u1", "name": "load_context", "status": "ok"}\n\n',
        'event: token\ndata: {"text": "Hi"}\n\n',
        'event: done\ndata: {"message_id": "m1", "turn_id": "u1", "usage": {}}\n\n',
      ]),
    );

    const events = await collect(streamChat("c1", "hi"));

    expect(events.map((e) => e.event)).toEqual(["activity", "token", "done"]);
    expect(events[0]).toMatchObject({ turn_id: "u1", name: "load_context" });
  });

  it("passes the tutor's cards through", async () => {
    mockFetch(
      sseResponse([
        'event: card\ndata: {"id": "k1", "turn_id": "u1", "kind": "link", "status": "info"}\n\n',
        'event: done\ndata: {"message_id": "m1", "turn_id": "u1", "usage": {}}\n\n',
      ]),
    );

    const events = await collect(streamChat("c1", "hi"));

    expect(events.map((e) => e.event)).toEqual(["card", "done"]);
    expect(events[0]).toMatchObject({ id: "k1", turn_id: "u1", kind: "link" });
  });

  it("ends on an error event", async () => {
    mockFetch(
      sseResponse([
        'event: token\ndata: {"text": "Hi"}\n\n',
        'event: error\ndata: {"code": "llm_unavailable", "message": "down"}\n\n',
      ]),
    );

    const events = await collect(streamChat("c1", "hi"));

    expect(events.at(-1)).toEqual({ event: "error", code: "llm_unavailable", message: "down" });
  });

  it("reports a stream that closes without done as interrupted", async () => {
    mockFetch(sseResponse(['event: token\ndata: {"text": "Hi"}\n\n']));

    const events = await collect(streamChat("c1", "hi"));

    expect(events.map((e) => e.event)).toEqual(["token", "error"]);
    expect(events[1]).toMatchObject({ code: "stream_interrupted" });
  });

  it("throws ApiError for errors before the stream starts", async () => {
    mockFetch(
      new Response(JSON.stringify({ detail: { code: "no_llm_configured", message: "x" } }), {
        status: 409,
      }),
    );

    const error = await collect(streamChat("c1", "hi")).catch((e: unknown) => e);

    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 409, code: "no_llm_configured" });
  });

  it("passes the abort signal to fetch", async () => {
    const fetch = mockFetch(sseResponse(['event: done\ndata: {"message_id": null, "usage": {}}\n\n']));
    const controller = new AbortController();

    await collect(streamChat("c1", "hi", { signal: controller.signal }));

    expect(fetch.mock.calls[0][1]?.signal).toBe(controller.signal);
  });
});

describe("streamChat against a real server", () => {
  it("aborting mid-reply rejects with AbortError and closes the connection", async () => {
    let serverSawClose!: () => void;
    const closed = new Promise<void>((resolve) => (serverSawClose = resolve));
    const server = createServer((_req, res) => {
      res.writeHead(200, { "content-type": "text/event-stream" });
      res.write('event: token\ndata: {"text": "Hi"}\n\n');
      const timer = setInterval(() => res.write('event: token\ndata: {"text": "."}\n\n'), 20);
      res.on("close", () => {
        clearInterval(timer);
        serverSawClose();
      });
    });
    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    const { port } = server.address() as AddressInfo;
    const realFetch = globalThis.fetch;
    vi.stubGlobal("fetch", (url: string, init?: RequestInit) =>
      realFetch(`http://127.0.0.1:${port}${url}`, init),
    );

    try {
      const controller = new AbortController();
      const seen: ChatEvent[] = [];
      const error = await (async () => {
        for await (const event of streamChat("c1", "hi", { signal: controller.signal })) {
          seen.push(event);
          if (seen.length === 3) controller.abort();
        }
      })().catch((e: unknown) => e);

      expect(error).toMatchObject({ name: "AbortError" });
      expect(seen.every((e) => e.event === "token")).toBe(true);
      await closed;
    } finally {
      server.close();
    }
  });
});
