import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import type { ChatEvent } from "@/lib/sse";

import { useChatSession } from "./use-chat-session";

const api = vi.hoisted(() => vi.fn());
const streamChat = vi.hoisted(() => vi.fn());
const streamOpening = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  api,
}));
vi.mock("@/lib/sse", () => ({ streamChat, streamOpening, OPENING_TURN_ID: "opening" }));

const CONVERSATION = { id: "c1", title: "", created_at: "", updated_at: "", focus_kc: null };

async function* events(...items: ChatEvent[]) {
  yield* items;
}

function setup(conversationId: string | null = null) {
  const onConversationCreated = vi.fn();
  const onTurnFinished = vi.fn();
  const onActivity = vi.fn();
  const onReplyDone = vi.fn();
  const hook = renderHook(
    ({ id }: { id: string | null }) =>
      useChatSession(id, { onConversationCreated, onTurnFinished, onActivity, onReplyDone }),
    { initialProps: { id: conversationId } },
  );
  return { ...hook, onConversationCreated, onTurnFinished, onActivity, onReplyDone };
}

beforeEach(() => {
  api.mockReset();
  streamChat.mockReset();
  streamOpening.mockReset();
});

describe("useChatSession", () => {
  it("creates the conversation lazily and streams the reply", async () => {
    api.mockResolvedValueOnce(CONVERSATION);
    const read = {
      turn_id: "u1",
      name: "load_context",
      kind: "step" as const,
      call_id: "",
      status: "ok" as const,
      duration_ms: 3,
      summary: { facts: ["f1"], episodes: [], profile_items: 0 },
    };
    streamChat.mockReturnValue(
      events(
        { event: "activity", ...read },
        { event: "token", text: "Hel" },
        { event: "token", text: "lo" },
        { event: "done", message_id: "m1", turn_id: "u1", usage: {} },
      ),
    );
    const { result, onConversationCreated, onTurnFinished, onActivity, onReplyDone, rerender } =
      setup();

    let sent: boolean | undefined;
    await act(async () => {
      sent = await result.current.send("Hi");
    });

    expect(sent).toBe(true);
    expect(api).toHaveBeenCalledWith("/conversations", { method: "POST" });
    expect(streamChat.mock.calls[0].slice(0, 2)).toEqual(["c1", "Hi"]);
    expect(onConversationCreated).toHaveBeenCalledWith(CONVERSATION);
    expect(onTurnFinished).toHaveBeenCalledOnce();
    expect(result.current.messages.map(({ role, content, status }) => [role, content, status])).toEqual([
      ["user", "Hi", undefined],
      ["assistant", "Hello", undefined],
    ]);
    expect(onActivity).toHaveBeenCalledWith(expect.objectContaining(read));
    expect(onReplyDone).toHaveBeenCalledWith("c1", "u1");
    expect(result.current.messages[1].turnId).toBe("u1");
    // The saved reply's id, for translating it.
    expect(result.current.messages[1].id).toBe("m1");

    // The page then switches to the new id: the on-screen turn must not be reloaded.
    rerender({ id: "c1" });
    expect(api).toHaveBeenCalledTimes(1);
    expect(result.current.messages).toHaveLength(2);
  });

  it("takes everything back when the first send is refused", async () => {
    api.mockResolvedValueOnce(CONVERSATION).mockResolvedValueOnce(undefined);
    streamChat.mockImplementation(async function* () {
      yield* [];
      throw new ApiError(409, "no_llm_configured", "configure a model");
    });
    const { result, onConversationCreated, onTurnFinished } = setup();

    let sent: boolean | undefined;
    await act(async () => {
      sent = await result.current.send("Hi");
    });

    expect(sent).toBe(false);
    expect(result.current.messages).toEqual([]);
    expect(result.current.error).toMatchObject({ code: "no_llm_configured" });
    expect(api).toHaveBeenLastCalledWith("/conversations/c1", { method: "DELETE" });
    expect(onConversationCreated).not.toHaveBeenCalled();
    expect(onTurnFinished).not.toHaveBeenCalled();
  });

  it("creates with the given function, and keeps a refused one that may already exist", async () => {
    const createConversation = vi.fn().mockResolvedValue({ ...CONVERSATION, purpose: "daily" });
    streamChat.mockImplementation(async function* () {
      yield* [];
      throw new ApiError(409, "no_llm_configured", "configure a model");
    });
    const { result } = renderHook(() =>
      useChatSession(null, {
        onConversationCreated: vi.fn(),
        onTurnFinished: vi.fn(),
        createConversation,
        discardRefused: false,
      }),
    );

    await act(async () => {
      await result.current.send("Hi");
    });

    expect(createConversation).toHaveBeenCalledTimes(1);
    expect(streamChat.mock.calls[0][0]).toBe("c1");
    // Today's conversation is reused, not deleted: it may hold earlier turns.
    expect(api).not.toHaveBeenCalled();
    expect(result.current.error).toMatchObject({ code: "no_llm_configured" });
  });

  it("marks the reply when the stream reports an error", async () => {
    api.mockResolvedValueOnce([]);
    streamChat.mockReturnValue(
      events(
        { event: "token", text: "Par" },
        { event: "error", code: "llm_unavailable", message: "down" },
      ),
    );
    const { result } = setup("c1");
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      await result.current.send("Hi");
    });

    expect(result.current.messages[1]).toMatchObject({
      content: "Par",
      status: "error",
      error: { code: "llm_unavailable" },
    });
  });

  it("stop aborts the stream and marks the partial reply", async () => {
    api.mockResolvedValueOnce([]);
    streamChat.mockImplementation(async function* (
      _id: string,
      _text: string,
      { signal }: { signal: AbortSignal },
    ) {
      yield { event: "token", text: "Half" } satisfies ChatEvent;
      await new Promise((_, reject) =>
        signal.addEventListener("abort", () =>
          reject(new DOMException("aborted", "AbortError")),
        ),
      );
    });
    const { result, onTurnFinished } = setup("c1");
    await waitFor(() => expect(result.current.loading).toBe(false));

    let sending!: Promise<boolean>;
    act(() => {
      sending = result.current.send("Hi");
    });
    await waitFor(() => expect(result.current.messages[1]?.content).toBe("Half"));
    expect(result.current.streaming).toBe(true);

    await act(async () => {
      result.current.stop();
      await sending;
    });

    expect(result.current.streaming).toBe(false);
    expect(result.current.messages[1]).toMatchObject({ content: "Half", status: "stopped" });
    expect(onTurnFinished).toHaveBeenCalledOnce();
  });

  it("loads history when opening an existing conversation", async () => {
    api.mockResolvedValueOnce([
      { id: "1", role: "user", content: "Hi" },
      { id: "2", role: "assistant", content: "Hello!" },
    ]);
    const { result } = setup("c9");

    await waitFor(() => expect(result.current.messages).toHaveLength(2));
    expect(api).toHaveBeenCalledWith("/conversations/c9/messages");
    // A reply's activity is filed under the learner message it answers.
    expect(result.current.messages.map((m) => m.turnId)).toEqual([undefined, "1"]);
    expect(result.current.messages.map((m) => m.id)).toEqual(["1", "2"]);
  });

  it("creates the conversation once when attachments need it before the first send", async () => {
    let resolve: (c: typeof CONVERSATION) => void = () => {};
    api.mockReturnValueOnce(new Promise((r) => (resolve = r)));
    const { result, onConversationCreated } = setup();

    let ids: string[] = [];
    await act(async () => {
      const both = Promise.all([
        result.current.ensureConversation(),
        result.current.ensureConversation(),
      ]);
      resolve(CONVERSATION);
      ids = await both;
    });

    expect(ids).toEqual(["c1", "c1"]);
    expect(api).toHaveBeenCalledOnce();
    expect(onConversationCreated).toHaveBeenCalledOnce();
  });

  it("sends attachment ids and shows a voice message as its transcript", async () => {
    api.mockResolvedValueOnce([]); // the conversation's (empty) history
    streamChat.mockReturnValue(
      events({ event: "done", message_id: "m1", turn_id: "u1", usage: {} }),
    );
    const { result } = setup("c1");
    await waitFor(() => expect(result.current.loading).toBe(false));
    const voice = {
      id: "a1",
      conversation_id: "c1",
      kind: "audio" as const,
      mime_type: "audio/webm",
      filename: "voice.webm",
      size_bytes: 1,
      status: "ready" as const,
      text: "I goed home.",
      meta: {},
      error: null,
      sent: false,
      created_at: "",
    };

    await act(async () => {
      await result.current.send("", [voice]);
    });

    expect(streamChat.mock.calls[0][2]).toMatchObject({ attachmentIds: ["a1"] });
    expect(result.current.messages[0]).toMatchObject({
      role: "user",
      content: "I goed home.",
      attachments: [voice],
    });
  });

  describe("practice opening", () => {
    it("is ready only once the conversation's history is loaded", async () => {
      let resolve: (history: unknown[]) => void = () => {};
      api.mockReturnValueOnce(new Promise((r) => (resolve = r)));
      const { result } = setup("p1");

      expect(result.current.readyFor).toBeNull();
      await act(async () => resolve([]));
      expect(result.current.readyFor).toBe("p1");
    });

    it("streams the tutor's first message", async () => {
      api.mockResolvedValueOnce([]);
      streamOpening.mockReturnValue(
        events(
          { event: "token", text: "Welcome!" },
          { event: "done", message_id: "a1", turn_id: "opening", usage: {} },
        ),
      );
      const { result, onTurnFinished, onReplyDone } = setup("p1");
      await waitFor(() => expect(result.current.readyFor).toBe("p1"));

      await act(() => result.current.open());

      expect(streamOpening.mock.calls[0][0]).toBe("p1");
      expect(result.current.messages.map(({ role, content, status, turnId }) => [role, content, status, turnId])).toEqual([
        ["assistant", "Welcome!", undefined, "opening"],
      ]);
      expect(onReplyDone).toHaveBeenCalledWith("p1", "opening");
      expect(onTurnFinished).toHaveBeenCalledOnce();
    });

    it("adds nothing when refused, and says why", async () => {
      api.mockResolvedValueOnce([]);
      streamOpening.mockImplementation(async function* () {
        yield* [];
        throw new ApiError(409, "no_llm_configured", "configure a model");
      });
      const { result, onTurnFinished } = setup("p1");
      await waitFor(() => expect(result.current.readyFor).toBe("p1"));

      await act(() => result.current.open());

      expect(result.current.messages).toEqual([]);
      expect(result.current.error?.code).toBe("no_llm_configured");
      expect(onTurnFinished).not.toHaveBeenCalled();
    });

    it("files a reloaded opening's activity under the opening", async () => {
      api.mockResolvedValueOnce([
        { id: "a1", role: "assistant", content: "Welcome!", attachments: [] },
        { id: "u1", role: "user", content: "I like tea.", attachments: [] },
        { id: "a2", role: "assistant", content: "Nice!", attachments: [] },
      ]);
      const { result } = setup("p1");

      await waitFor(() => expect(result.current.messages).toHaveLength(3));
      expect(result.current.messages.map((m) => m.turnId)).toEqual(["opening", undefined, "u1"]);
    });
  });
});
