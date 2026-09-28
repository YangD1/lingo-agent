"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import type { ApiErrorLike } from "@/i18n/errors";
import { api, ApiError, isAbortError } from "@/lib/api";
import { streamChat } from "@/lib/sse";
import type { Conversation, HistoryMessage } from "@/lib/types";

export type ChatMessage = {
  key: string;
  role: "user" | "assistant";
  content: string;
  /** streaming: tokens still arriving; stopped: user pressed stop; error: see `error`. */
  status?: "streaming" | "stopped" | "error";
  error?: ApiErrorLike;
};

type Options = {
  /** Called once a lazily created conversation exists, so the page can update URL/list. */
  onConversationCreated: (conversation: Conversation) => void;
  /** Called after a reply finishes (the backend retitled/bumped the conversation). */
  onTurnFinished: () => void;
};

const toApiErrorLike = (error: unknown): ApiErrorLike =>
  error instanceof ApiError ? error : { code: "network_error", message: String(error) };

let keySeq = 0;
const nextKey = () => `m${++keySeq}`;

export function useChatSession(conversationId: string | null, options: Options) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [loading, setLoading] = useState(false);
  const [streaming, setStreaming] = useState(false);
  /** An error before any reply was produced (e.g. no_llm_configured); the input is restored. */
  const [error, setError] = useState<ApiErrorLike | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  // A conversation we just created mid-send already has its messages on screen.
  const createdIdRef = useRef<string | null>(null);
  const optionsRef = useRef(options);
  useEffect(() => {
    optionsRef.current = options;
  });

  useEffect(() => {
    // We just created this conversation mid-send: its turn is streaming, don't touch it.
    if (conversationId !== null && conversationId === createdIdRef.current) {
      createdIdRef.current = null; // skip once; switching back later reloads history
      return;
    }
    abortRef.current?.abort();
    setError(null);
    if (conversationId === null) {
      setMessages([]);
      return;
    }
    let cancelled = false;
    setLoading(true);
    api<HistoryMessage[]>(`/conversations/${conversationId}/messages`)
      .then((history) => {
        if (!cancelled) {
          setMessages(history.map((m) => ({ key: nextKey(), role: m.role, content: m.content })));
        }
      })
      .catch((e: unknown) => !cancelled && setError(toApiErrorLike(e)))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [conversationId]);

  useEffect(() => () => abortRef.current?.abort(), []);

  const updateLast = (patch: (message: ChatMessage) => ChatMessage) =>
    setMessages((all) => [...all.slice(0, -1), patch(all[all.length - 1])]);

  /** Returns false if nothing was sent, so the caller keeps the text in the input box. */
  const send = useCallback(
    async (text: string): Promise<boolean> => {
      const controller = new AbortController();
      abortRef.current = controller;
      setError(null);
      setStreaming(true);
      // Optimistic: show the message now, take it back if the backend refuses the turn.
      setMessages((all) => [
        ...all,
        { key: nextKey(), role: "user", content: text },
        { key: nextKey(), role: "assistant", content: "", status: "streaming" },
      ]);
      let created: Conversation | null = null;
      let accepted = false;
      try {
        let id = conversationId;
        if (id === null) {
          created = await api<Conversation>("/conversations", { method: "POST" });
          id = createdIdRef.current = created.id;
        }
        const stream = streamChat(id, text, { signal: controller.signal });
        let step = await stream.next(); // 404/409 throw here, before any reply
        accepted = true;
        if (created) optionsRef.current.onConversationCreated(created);
        for (; !step.done; step = await stream.next()) {
          const event = step.value;
          if (event.event === "token") {
            updateLast((m) => ({ ...m, content: m.content + event.text }));
          } else if (event.event === "done") {
            updateLast((m) => ({ ...m, status: undefined }));
          } else {
            updateLast((m) => ({ ...m, status: "error", error: event }));
          }
        }
        return true;
      } catch (e) {
        if (accepted) {
          // Stopped or cut off mid-reply. The backend keeps the user's message but not
          // the partial reply (ADR 0003), so mark it instead of pretending it was saved.
          updateLast((m) =>
            isAbortError(e)
              ? { ...m, status: "stopped" }
              : { ...m, status: "error", error: toApiErrorLike(e) },
          );
          return true;
        }
        setMessages((all) => all.slice(0, -2));
        if (created) {
          // Don't leave an empty conversation behind when its first send was refused.
          createdIdRef.current = null;
          await api(`/conversations/${created.id}`, { method: "DELETE" }).catch(() => {});
        }
        if (!isAbortError(e)) setError(toApiErrorLike(e));
        return false;
      } finally {
        if (abortRef.current === controller) abortRef.current = null;
        setStreaming(false);
        if (accepted) optionsRef.current.onTurnFinished();
      }
    },
    [conversationId],
  );

  const stop = useCallback(() => abortRef.current?.abort(), []);

  return { messages, loading, streaming, error, send, stop };
}
