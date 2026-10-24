"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import type { ApiErrorLike } from "@/i18n/errors";
import type { Activity } from "@/lib/activity";
import { api, ApiError, isAbortError } from "@/lib/api";
import type { TutorCard } from "@/lib/cards";
import { type RunWatcher, stopRun, trackRun, unwatchRun, watchRun } from "@/lib/chat-runs";
import {
  ended,
  type FollowUp,
  fromHistory,
  started,
  stoppedWhileWriting,
  withToken,
  writing,
} from "@/lib/follow-ups";
import { type ChatEvent, OPENING_TURN_ID, streamChat, streamOpening } from "@/lib/sse";
import type { Attachment, Conversation, HistoryMessage } from "@/lib/types";
import { usePetHold } from "@/lib/tutor-pet";

export type ChatMessage = {
  key: string;
  /** The backend's id, once saved (what translating a reply needs). */
  id?: string;
  role: "user" | "assistant";
  content: string;
  attachments?: Attachment[];
  /** streaming: tokens still arriving; stopped: user pressed stop; error: see `error`. */
  status?: "streaming" | "stopped" | "error";
  error?: ApiErrorLike;
  /** On replies: the learner message they answer, which their activity is filed under. */
  turnId?: string;
  /** When it joined the conversation (ADR 0044 §5): the backend's stamp, or this browser's
   * clock for one sent or streamed here; absent for messages saved before stamps. */
  createdAt?: string;
  /** On replies: the tutor's follow-ups under it (ADR 0064 §7), in its `content`. */
  followUps?: FollowUp[];
};

type Options = {
  /** Called once a lazily created conversation exists, so the page can update URL/list. */
  onConversationCreated: (conversation: Conversation) => void;
  /** Called after a reply finishes (the backend retitled/bumped the conversation). */
  onTurnFinished: () => void;
  /** Each piece of the reply as it streams in (the speaking page reads it aloud). */
  onToken?: (text: string) => void;
  /** A step of the turn, streamed while the reply is generated (ADR 0013 §3). */
  onActivity?: (activity: Activity) => void;
  /** A card the tutor showed with a tool call during the reply (ADR 0015). */
  onCard?: (card: TutorCard) => void;
  /** The reply was saved; its background activity follows under `turnId`. */
  onReplyDone?: (conversationId: string, turnId: string) => void;
  /** How a new chat's conversation is created; a plain one by default. */
  createConversation?: () => Promise<Conversation>;
  /**
   * False when `createConversation` may return one that already exists (today's daily
   * conversation): a refused first send then keeps it; an empty one is reused anyway.
   */
  discardRefused?: boolean;
  /** The document open in the workspace beside the chat, sent with each message. */
  workspaceDocId?: string | null;
};

const toApiErrorLike = (error: unknown): ApiErrorLike =>
  error instanceof ApiError ? error : { code: "network_error", message: String(error) };

/** Retrying a send the backend refused while the reply it follows was still letting go. */
const BUSY_RETRIES = 10;
const BUSY_RETRY_MS = 300;

const createPlain = () => api<Conversation>("/conversations", { method: "POST" });

let keySeq = 0;
const nextKey = () => `m${++keySeq}`;

/** This view watching one conversation's reply (`lib/chat-runs.ts`), until it leaves. */
type Watch = { id: string; watcher: RunWatcher; unwatch: () => void; left: Promise<void> };

const toMessages = (history: HistoryMessage[]): ChatMessage[] =>
  history.map((m, i) => ({
    key: nextKey(),
    id: m.id ?? undefined,
    role: m.role,
    content: m.content,
    attachments: m.attachments,
    createdAt: m.created_at ?? undefined,
    followUps: fromHistory(m.follow_ups),
    turnId:
      m.role === "assistant" && history[i - 1]?.role === "user"
        ? (history[i - 1].id ?? undefined)
        : m.role === "assistant" && i === 0
          ? OPENING_TURN_ID // a practice or planning opening
          : undefined,
  }));

export function useChatSession(conversationId: string | null, options: Options) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [loading, setLoading] = useState(false);
  const [streaming, setStreaming] = useState(false);
  /** An error before any reply was produced (e.g. no_llm_configured); the input is restored. */
  const [error, setError] = useState<ApiErrorLike | null>(null);
  // The conversation whose history was loaded last: until it is the current one,
  // `messages` may still be another conversation's.
  const [loadedFor, setLoadedFor] = useState<string | null>(null);
  // A send or opening the backend has not taken yet: the stop button aborts it. Once taken,
  // the reply is the app's (ADR 0058 §1): leaving goes on with it, stop goes to `stopRun`.
  const abortRef = useRef<AbortController | null>(null);
  const watchRef = useRef<Watch | null>(null);
  // An in-flight creation, so two early uploads don't create two conversations.
  const creatingRef = useRef<Promise<string> | null>(null);
  // A conversation we just created mid-send already has its messages on screen.
  const createdIdRef = useRef<string | null>(null);
  const optionsRef = useRef(options);
  useEffect(() => {
    optionsRef.current = options;
  });
  const last = messages.at(-1);
  // A follow-up being written: the learner may send meanwhile (ADR 0064 §6).
  const followingUp = streaming && last?.role === "assistant" && writing(last.followUps) !== undefined;
  const followingUpRef = useRef(followingUp);
  useEffect(() => {
    followingUpRef.current = followingUp;
  });


  const updateLast = useCallback(
    (patch: (message: ChatMessage) => ChatMessage) =>
      setMessages((all) => [...all.slice(0, -1), patch(all[all.length - 1])]),
    [],
  );

  /** Apply one event of the reply being streamed into the last message. */
  const apply = useCallback(
    (event: ChatEvent, id: string, replay = false) => {
      if (event.event === "token") {
        updateLast((m) => ({
          ...m,
          content: m.content + event.text,
          followUps: withToken(m.followUps, m.content, event.text),
        }));
        // Not read aloud again when coming back to a reply already under way.
        if (!replay) optionsRef.current.onToken?.(event.text);
      } else if (event.event === "activity") {
        updateLast((m) => ({ ...m, turnId: event.turn_id }));
        optionsRef.current.onActivity?.(event);
      } else if (event.event === "card") {
        updateLast((m) => ({ ...m, turnId: event.turn_id }));
        optionsRef.current.onCard?.(event); // the card's fields, plus `event`
      } else if (event.event === "segment") {
        const { index } = event;
        updateLast((m) => ({
          ...m,
          followUps:
            event.state === "started"
              ? started(m.followUps, index, Date.now())
              : ended(m.followUps, index, event.outcome ?? "done"),
        }));
      } else if (event.event === "done") {
        const turnId = event.turn_id ?? undefined;
        setMessages((all) =>
          all.map((m, i) => {
            if (i === all.length - 1) {
              return { ...m, id: event.message_id ?? m.id, status: undefined, turnId: turnId ?? m.turnId };
            }
            // The learner message it answers is saved under the turn's id.
            if (i === all.length - 2 && m.role === "user" && !m.id && turnId !== OPENING_TURN_ID) {
              return { ...m, id: turnId };
            }
            return m;
          }),
        );
        if (turnId) optionsRef.current.onReplyDone?.(id, turnId);
      } else {
        updateLast((m) => ({ ...m, status: "error", error: event }));
      }
    },
    [updateLast],
  );

  /**
   * Stopped or cut off mid-reply: the partial reply isn't saved (ADR 0003), say so. Stopped
   * while a follow-up was written, the reply stays and only that follow-up goes (ADR 0064 §6).
   */
  const markInterrupted = useCallback(
    (e: unknown) =>
      updateLast((m) =>
        isAbortError(e) && m.followUps && writing(m.followUps)
          ? { ...m, ...stoppedWhileWriting(m.content, m.followUps), status: undefined }
          : isAbortError(e)
            ? { ...m, status: "stopped" }
            : { ...m, status: "error", error: toApiErrorLike(e) },
      ),
    [updateLast],
  );

  /** Stops watching the reply on screen, if any: it goes on being written (ADR 0058 §1). */
  const leave = useCallback(() => {
    const watch = watchRef.current;
    watchRef.current = null;
    watch?.unwatch();
  }, []);

  /** A watcher of `id`'s reply for this view: its events go on screen, its end finishes it. */
  const watchFor = useCallback(
    (id: string) => {
      let gone = () => {};
      const left = new Promise<void>((resolve) => (gone = resolve));
      const watcher: RunWatcher = {
        event: (event) => apply(event, id),
        end: (thrown) => {
          if (watchRef.current?.watcher === watcher) watchRef.current = null;
          gone();
          // Stopped or cut off mid-reply: the backend keeps the learner's message only.
          if (thrown !== undefined) markInterrupted(thrown);
          setStreaming(false);
          optionsRef.current.onTurnFinished();
        },
      };
      const watch: Watch = {
        id,
        watcher,
        left,
        unwatch: () => {
          unwatchRun(id, watcher);
          gone();
        },
      };
      return { watch, found: watchRun(id, watcher).found };
    },
    [apply, markInterrupted],
  );

  /** Hands a reply the backend took to the app; resolves once it ended or we left it. */
  const follow = useCallback(
    async (
      id: string,
      kind: "reply" | "opening",
      controller: AbortController,
      first: ChatEvent,
      stream: AsyncGenerator<ChatEvent, void, undefined>,
    ) => {
      if (abortRef.current === controller) abortRef.current = null;
      const { watch } = watchFor(id); // nothing running yet: only registers below
      watchRef.current = watch;
      await Promise.race([trackRun(id, kind, controller, first, stream, watch.watcher), watch.left]);
    },
    [watchFor],
  );

  useEffect(() => {
    // We just created this conversation mid-send: its turn is streaming, don't touch it.
    if (conversationId !== null && conversationId === createdIdRef.current) {
      createdIdRef.current = null; // skip once; switching back later reloads history
      return;
    }
    // Leaving: a reply not yet taken is dropped, one being written goes on without us.
    abortRef.current?.abort();
    leave();
    creatingRef.current = null;
    setError(null);
    if (conversationId === null) {
      // Switching to a new chat clears the screen, like the rest of this reset.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setMessages([]);
      setStreaming(false);
      return;
    }
    setStreaming(false);
    const id = conversationId;
    let cancelled = false;
    const load = async (): Promise<void> => {
      const since = Date.now();
      const history = await api<HistoryMessage[]>(`/conversations/${id}/messages`);
      if (cancelled) return;
      // A reply still being written here (sent before we left): shown so far, then on.
      const { watch, found } = watchFor(id);
      if (found?.running) {
        watchRef.current = watch;
        setMessages([
          ...toMessages(history),
          {
            key: nextKey(),
            createdAt: new Date().toISOString(),
            role: "assistant",
            content: "",
            status: "streaming",
            turnId: found.kind === "opening" ? OPENING_TURN_ID : undefined,
          },
        ]);
        setStreaming(true);
        for (const event of found.events) apply(event, id, true);
      } else if (found && found.endedAt >= since) {
        return load(); // it ended while the history was on its way: that may lack it
      } else {
        setMessages(toMessages(history));
      }
      setLoadedFor(id);
    };
    setLoading(true);
    load()
      .catch((e: unknown) => !cancelled && setError(toApiErrorLike(e)))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
    // `apply`, `leave` and `watchFor` are stable.
  }, [conversationId]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(
    () => () => {
      abortRef.current?.abort();
      leave();
    },
    [], // eslint-disable-line react-hooks/exhaustive-deps
  );

  /**
   * The conversation's id, creating it first if this is a new chat: attachments are
   * uploaded into a conversation before the message carrying them is sent (ADR 0008 §3).
   */
  const ensureConversation = useCallback(async (): Promise<string> => {
    if (conversationId !== null) return conversationId;
    creatingRef.current ??= (optionsRef.current.createConversation ?? createPlain)().then(
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
      // One reply at a time per conversation: stop the follow-up first, its reply stays.
      const interrupted = followingUpRef.current ? watchRef.current : null;
      if (interrupted) {
        stopRun(interrupted.id);
        await interrupted.left;
      }
      const controller = new AbortController();
      abortRef.current = controller;
      setError(null);
      setStreaming(true);
      // Optimistic: show the message now, take it back if the backend refuses the turn.
      const now = new Date().toISOString();
      setMessages((all) => [
        ...all,
        {
          key: nextKey(),
          createdAt: now,
          role: "user",
          // Like the backend: a voice message sent without typing reads as its transcript.
          content: text || (attachments.find((a) => a.kind === "audio")?.text ?? ""),
          attachments,
        },
        { key: nextKey(), createdAt: now, role: "assistant", content: "", status: "streaming" },
      ]);
      let created: Conversation | null = null;
      let accepted = false;
      try {
        let id = conversationId ?? (await creatingRef.current);
        if (id == null) {
          created = await (optionsRef.current.createConversation ?? createPlain)();
          id = createdIdRef.current = created.id;
        }
        let stream: AsyncGenerator<ChatEvent, void, undefined>;
        let step: IteratorResult<ChatEvent, void>;
        for (let tries = 0; ; tries++) {
          stream = streamChat(id, text, {
            signal: controller.signal,
            attachmentIds: attachments.map((a) => a.id),
            workspaceDocId: optionsRef.current.workspaceDocId,
          });
          try {
            step = await stream.next(); // 404/409 throw here, before any reply
            break;
          } catch (e) {
            // The stopped reply holds the conversation until the backend sees it gone.
            const busy = e instanceof ApiError && e.code === "conversation_busy";
            if (!interrupted || !busy || tries >= BUSY_RETRIES) throw e;
            await new Promise((resolve) => setTimeout(resolve, BUSY_RETRY_MS));
            controller.signal.throwIfAborted();
          }
        }
        accepted = true;
        if (created) optionsRef.current.onConversationCreated(created);
        if (!step.done) await follow(id, "reply", controller, step.value, stream);
        return true;
      } catch (e) {
        setMessages((all) => all.slice(0, -2));
        if (created) createdIdRef.current = null;
        if (created && optionsRef.current.discardRefused !== false) {
          // Don't leave an empty conversation behind when its first send was refused.
          await api(`/conversations/${created.id}`, { method: "DELETE" }).catch(() => {});
        }
        if (!isAbortError(e)) setError(toApiErrorLike(e));
        return false;
      } finally {
        if (abortRef.current === controller) abortRef.current = null;
        if (!accepted) setStreaming(false);
      }
    },
    [conversationId, follow],
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
      {
        key: nextKey(),
        createdAt: new Date().toISOString(),
        role: "assistant",
        content: "",
        status: "streaming",
        turnId: OPENING_TURN_ID,
      },
    ]);
    let accepted = false;
    try {
      const stream = streamOpening(id, { signal: controller.signal });
      const step = await stream.next(); // 409 throws here, before any reply
      accepted = true;
      if (!step.done) await follow(id, "opening", controller, step.value, stream);
    } catch (e) {
      setMessages((all) => all.slice(0, -1));
      if (!isAbortError(e)) setError(toApiErrorLike(e));
    } finally {
      if (abortRef.current === controller) abortRef.current = null;
      if (!accepted) setStreaming(false);
    }
  }, [conversationId, follow]);

  const stop = useCallback(() => {
    abortRef.current?.abort();
    if (watchRef.current) stopRun(watchRef.current.id);
  }, []);

  // Waiting on the tutor's first words: the desk pet thinks (ADR 0032 §4a).
  usePetHold("thinking", streaming && last?.role === "assistant" && last.content === "");

  /** The conversation whose history is on screen, once it is; null before that. */
  const readyFor = loadedFor === conversationId ? conversationId : null;

  return {
    messages,
    loading,
    streaming,
    followingUp,
    error,
    readyFor,
    send,
    open,
    stop,
    ensureConversation,
  };
}
