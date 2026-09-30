"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import type { ApiErrorLike } from "@/i18n/errors";
import type { Activity } from "@/lib/activity";
import { api, ApiError, isAbortError } from "@/lib/api";
import type { TutorCard } from "@/lib/cards";
import { type ChatEvent, OPENING_TURN_ID, streamChat, streamOpening } from "@/lib/sse";
import type { Attachment, Conversation, HistoryMessage } from "@/lib/types";

export type ChatMessage = {
  key: string;
  role: "user" | "assistant";
  content: string;
  attachments?: Attachment[];
  /** streaming: tokens still arriving; stopped: user pressed stop; error: see `error`. */
  status?: "streaming" | "stopped" | "error";
  error?: ApiErrorLike;
  /** On replies: the learner message they answer, which their activity is filed under. */
  turnId?: string;
};

type Options = {
  /** Called once a lazily created conversation exists, so the page can update URL/list. */
  onConversationCreated: (conversation: Conversation) => void;
  /** Called after a reply finishes (the backend retitled/bumped the conversation). */
  onTurnFinished: () => void;
  /** A step of the turn, streamed while the reply is generated (ADR 0013 §3). */
  onActivity?: (activity: Activity) => void;
  /** A card the tutor showed with a tool call during the reply (ADR 0015). */
  onCard?: (card: TutorCard) => void;
  /** The reply was saved; its background activity follows under `turnId`. */
  onReplyDone?: (conversationId: string, turnId: string) => void;
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
  // The conversation whose history was loaded last: until it is the current one,
  // `messages` may still be another conversation's.
  const [loadedFor, setLoadedFor] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  // An in-flight creation, so two early uploads don't create two conversations.
  const creatingRef = useRef<Promise<string> | null>(null);
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
    creatingRef.current = null;
    setError(null);
    if (conversationId === null) {
      // Switching to a new chat clears the screen, like the rest of this reset.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setMessages([]);
      return;
    }
    let cancelled = false;
    setLoading(true);
    api<HistoryMessage[]>(`/conversations/${conversationId}/messages`)
      .then((history) => {
        if (!cancelled) {
          setMessages(
            history.map((m, i) => ({
              key: nextKey(),
              role: m.role,
              content: m.content,
              attachments: m.attachments,
              turnId:
                m.role === "assistant" && history[i - 1]?.role === "user"
                  ? (history[i - 1].id ?? undefined)
                  : m.role === "assistant" && i === 0
                    ? OPENING_TURN_ID // a practice or planning opening
                    : undefined,
            })),
          );
          setLoadedFor(conversationId);
        }
      })
      .catch((e: unknown) => !cancelled && setError(toApiErrorLike(e)))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [conversationId]);

  useEffect(() => () => abortRef.current?.abort(), []);

  const updateLast = useCallback(
    (patch: (message: ChatMessage) => ChatMessage) =>
      setMessages((all) => [...all.slice(0, -1), patch(all[all.length - 1])]),
    [],
  );

  /** Apply one event of the reply being streamed into the last message. */
  const apply = useCallback(
    (event: ChatEvent, id: string) => {
      if (event.event === "token") {
        updateLast((m) => ({ ...m, content: m.content + event.text }));
      } else if (event.event === "activity") {
        updateLast((m) => ({ ...m, turnId: event.turn_id }));
        optionsRef.current.onActivity?.(event);
      } else if (event.event === "card") {
        updateLast((m) => ({ ...m, turnId: event.turn_id }));
        optionsRef.current.onCard?.(event); // the card's fields, plus `event`
      } else if (event.event === "done") {
        const turnId = event.turn_id ?? undefined;
        updateLast((m) => ({ ...m, status: undefined, turnId: turnId ?? m.turnId }));
        if (turnId) optionsRef.current.onReplyDone?.(id, turnId);
      } else {
        updateLast((m) => ({ ...m, status: "error", error: event }));
      }
    },
    [updateLast],
  );

  /** Stopped or cut off mid-reply: the partial reply isn't saved (ADR 0003), say so. */
  const markInterrupted = useCallback(
    (e: unknown) =>
      updateLast((m) =>
        isAbortError(e)
          ? { ...m, status: "stopped" }
          : { ...m, status: "error", error: toApiErrorLike(e) },
      ),
    [updateLast],
  );

  /**
   * The conversation's id, creating it first if this is a new chat: attachments are
   * uploaded into a conversation before the message carrying them is sent (ADR 0008 §3).
   */
  const ensureConversation = useCallback(async (): Promise<string> => {
    if (conversationId !== null) return conversationId;
    creatingRef.current ??= api<Conversation>("/conversations", { method: "POST" }).then(
      (created) => {
        createdIdRef.current = created.id;
        optionsRef.current.onConversationCreated(created);
        return created.id;
      },
      (e: unknown) => {
        creatingRef.current = null;
        throw e;
      },
    );
    return creatingRef.current;
  }, [conversationId]);

  /** Returns false if nothing was sent, so the caller keeps the text in the input box. */
  const send = useCallback(
    async (text: string, attachments: Attachment[] = []): Promise<boolean> => {
      const controller = new AbortController();
      abortRef.current = controller;
      setError(null);
      setStreaming(true);
      // Optimistic: show the message now, take it back if the backend refuses the turn.
      setMessages((all) => [
        ...all,
        {
          key: nextKey(),
          role: "user",
          // Like the backend: a voice message sent without typing reads as its transcript.
          content: text || (attachments.find((a) => a.kind === "audio")?.text ?? ""),
          attachments,
        },
        { key: nextKey(), role: "assistant", content: "", status: "streaming" },
      ]);
      let created: Conversation | null = null;
      let accepted = false;
      try {
        let id = conversationId ?? (await creatingRef.current);
        if (id == null) {
          created = await api<Conversation>("/conversations", { method: "POST" });
          id = createdIdRef.current = created.id;
        }
        const stream = streamChat(id, text, {
          signal: controller.signal,
          attachmentIds: attachments.map((a) => a.id),
        });
        let step = await stream.next(); // 404/409 throw here, before any reply
        accepted = true;
        if (created) optionsRef.current.onConversationCreated(created);
        for (; !step.done; step = await stream.next()) apply(step.value, id);
        return true;
      } catch (e) {
        if (accepted) {
          // The backend keeps the learner's message, not the partial reply.
          markInterrupted(e);
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
    [conversationId, apply, markInterrupted],
  );

  /**
   * Have the tutor open a practice or planning conversation that has no messages yet
   * (Q19a, ADR 0015 §6). A refusal (no model, already started) shows as `error` and
   * adds nothing.
   */
  const open = useCallback(async (): Promise<void> => {
    if (conversationId === null) return;
    const id = conversationId;
    const controller = new AbortController();
    abortRef.current = controller;
    setError(null);
    setStreaming(true);
    setMessages((all) => [
      ...all,
      { key: nextKey(), role: "assistant", content: "", status: "streaming", turnId: OPENING_TURN_ID },
    ]);
    let accepted = false;
    try {
      const stream = streamOpening(id, { signal: controller.signal });
      let step = await stream.next(); // 409 throws here, before any reply
      accepted = true;
      for (; !step.done; step = await stream.next()) apply(step.value, id);
    } catch (e) {
      if (accepted) {
        markInterrupted(e);
      } else {
        setMessages((all) => all.slice(0, -1));
        if (!isAbortError(e)) setError(toApiErrorLike(e));
      }
    } finally {
      if (abortRef.current === controller) abortRef.current = null;
      setStreaming(false);
      if (accepted) optionsRef.current.onTurnFinished();
    }
  }, [conversationId, apply, markInterrupted]);

  const stop = useCallback(() => abortRef.current?.abort(), []);

  /** The conversation whose history is on screen, once it is; null before that. */
  const readyFor = loadedFor === conversationId ? conversationId : null;

  return { messages, loading, streaming, error, readyFor, send, open, stop, ensureConversation };
}
