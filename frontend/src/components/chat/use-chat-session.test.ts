import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import type { ChatEvent } from "@/lib/sse";

import { useChatSession } from "./use-chat-session";

const api = vi.hoisted(() => vi.fn());
const streamChat = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  api,
}));
vi.mock("@/lib/sse", () => ({ streamChat }));

const CONVERSATION = { id: "c1", title: "", created_at: "", updated_at: "" };

async function* events(...items: ChatEvent[]) {
  yield* items;
}

function setup(conversationId: string | null = null) {
  const onConversationCreated = vi.fn();
  const onTurnFinished = vi.fn();
  const hook = renderHook(
    ({ id }: { id: string | null }) => useChatSession(id, { onConversationCreated, onTurnFinished }),
    { initialProps: { id: conversationId } },
  );
  return { ...hook, onConversationCreated, onTurnFinished };
}

beforeEach(() => {
  api.mockReset();
  streamChat.mockReset();
});

describe("useChatSession", () => {
  it("creates the conversation lazily and streams the reply", async () => {
    api.mockResolvedValueOnce(CONVERSATION);
    streamChat.mockReturnValue(
      events(
        { event: "token", text: "Hel" },
        { event: "token", text: "lo" },
        { event: "done", message_id: "m1", usage: {} },
      ),
    );
    const { result, onConversationCreated, onTurnFinished, rerender } = setup();

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
  });
});
