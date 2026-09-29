"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import {
  type Activity,
  type ConversationActivity,
  fetchActivity,
  type KCRef,
  type MemoryRef,
  mergeActivities,
  type WordsCollected,
} from "@/lib/activity";
import { ApiError } from "@/lib/api";
import { removeMine } from "@/lib/vocab";

/** After a reply: when to look for the background results, in ms from `done`. */
export const POLL_DELAYS = [2000, 4000, 8000, 15000, 25000, 40000, 60000];

export type ActivityState = {
  byTurn: Record<string, Activity[]>;
  memories: Record<string, MemoryRef>;
  kcs: Record<string, KCRef>;
  /** Whether each collected word is still on the learner's word list. */
  wordsOnList: Record<number, boolean>;
  /** Turns whose background results are still being waited for. */
  waiting: Set<string>;
};

/** What the chat shows, and the one change it can make: taking a collected word off
 * the word list again. */
export type ActivityView = ActivityState & { removeWord: (wordId: number) => Promise<void> };

const EMPTY: ActivityState = {
  byTurn: {},
  memories: {},
  kcs: {},
  wordsOnList: {},
  waiting: new Set(),
};

/** State of one conversation; a switch starts from EMPTY without an effect resetting it. */
type Owned = ActivityState & { conversationId: string | null };

const own = (s: Owned, id: string | null): Owned =>
  s.conversationId === id ? s : { ...EMPTY, conversationId: id };

function absorb(state: Owned, body: ConversationActivity): Owned {
  const byTurn = { ...state.byTurn };
  const wordsOnList = { ...state.wordsOnList };
  for (const a of body.activities) {
    byTurn[a.turn_id] = mergeActivities(byTurn[a.turn_id] ?? [], [a]);
    if (a.name !== "vocab_collect" || a.status !== "ok") continue;
    for (const w of (a.summary as WordsCollected).added ?? []) {
      wordsOnList[w.word_id] = body.words_on_list.includes(w.word_id);
    }
  }
  return {
    ...state,
    byTurn,
    memories: { ...state.memories, ...body.memories },
    kcs: { ...state.kcs, ...body.kcs },
    wordsOnList,
  };
}

/**
 * What the tutor did on each turn of a conversation (ADR 0013 §3): loaded with the
 * conversation, steps streamed live, and background results polled for after a reply.
 * `enabled: false` (the learner hid it) fetches nothing.
 */
export function useActivity(conversationId: string | null, enabled: boolean) {
  const [owned, setOwned] = useState<Owned>({ ...EMPTY, conversationId });
  const timers = useRef(new Set<ReturnType<typeof setTimeout>>());
  // The conversation on screen. Results for another one are dropped, and its polls stop.
  // (Not cleared on switching: a new chat's reply can finish before its id arrives.)
  const current = useRef(conversationId);
  useEffect(() => {
    current.current = conversationId;
  });
  // Updates always apply to the conversation on screen.
  const setState = useCallback(
    (update: (s: Owned) => Owned) => setOwned((s) => update(own(s, current.current))),
    [],
  );

  const poll = useCallback(
    (id: string, turnId: string) => {
      const stopWaiting = () =>
        setState((s) => {
          const waiting = new Set(s.waiting);
          waiting.delete(turnId);
          return { ...s, waiting };
        });
      setState((s) => ({ ...s, waiting: new Set(s.waiting).add(turnId) }));
      const attempt = (i: number) => {
        const timer = setTimeout(async () => {
          timers.current.delete(timer);
          let pending = true;
          try {
            const body = await fetchActivity(id, [turnId]);
            if (current.current !== id) return;
            setState((s) => absorb(s, body));
            pending = body.pending;
          } catch {
            // A failed poll is retried by the next one.
          }
          if (current.current !== id) return;
          if (pending && i + 1 < POLL_DELAYS.length) attempt(i + 1);
          else stopWaiting();
        }, POLL_DELAYS[i] - (i ? POLL_DELAYS[i - 1] : 0));
        timers.current.add(timer);
      };
      attempt(0);
    },
    [setState],
  );

  useEffect(() => {
    if (!enabled || conversationId === null) return;
    fetchActivity(conversationId).then(
      (body) => current.current === conversationId && setState((s) => absorb(s, body)),
      () => {},
    );
  }, [conversationId, enabled, setState]);

  useEffect(() => {
    const pending = timers.current;
    return () => {
      for (const t of pending) clearTimeout(t);
    };
  }, []);

  /** A step streamed during the reply. */
  const addLive = useCallback(
    (activity: Activity) =>
      setState((s) => ({
        ...s,
        byTurn: {
          ...s.byTurn,
          [activity.turn_id]: mergeActivities(s.byTurn[activity.turn_id] ?? [], [activity]),
        },
      })),
    [setState],
  );

  /** The reply is done: its background results follow shortly. */
  const turnFinished = useCallback(
    (id: string, turnId: string) => {
      if (enabled) poll(id, turnId);
    },
    [enabled, poll],
  );

  /** Undo collecting a word; already gone (removed on /vocab/mine) counts as done. */
  const removeWord = useCallback(
    async (wordId: number) => {
      try {
        await removeMine(wordId);
      } catch (err) {
        if (!(err instanceof ApiError && err.status === 404)) throw err;
      }
      setState((s) => ({ ...s, wordsOnList: { ...s.wordsOnList, [wordId]: false } }));
    },
    [setState],
  );

  const { byTurn, memories, kcs, wordsOnList, waiting } = own(owned, conversationId);
  return { byTurn, memories, kcs, wordsOnList, waiting, removeWord, addLive, turnFinished };
}
