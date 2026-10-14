import { useEffect, useSyncExternalStore } from "react";

import { api } from "@/lib/api";
import type { Conversation } from "@/lib/types";
import { browserTimeZone } from "@/lib/vocab";

function timeZoneQuery(): string {
  const tz = browserTimeZone();
  return tz ? `?${new URLSearchParams({ tz })}` : "";
}

/** Today's conversation (ADR 0016 §1), or null before it is created. */
export const fetchToday = () => api<Conversation | null>(`/conversations/today${timeZoneQuery()}`);

/** Today's conversation, created if there is none yet; one a day. */
export const createToday = (locale: string) =>
  api<Conversation>("/conversations", {
    method: "POST",
    json: { purpose: "daily", locale, tz: browserTimeZone() },
  });

/** Today's conversation and whether anything has been said in it yet. */
export type Today = { conversation: Conversation | null; started: boolean };

/** Looked at again on focus once this old: it may have begun in another tab. */
const STALE_MS = 60_000;

// One answer for the pet and its window, for the local day it was found on.
let known: { day: string; at: number; today: Today } | null = null;
let checking: Promise<void> | null = null;
const listeners = new Set<() => void>();

function localDay(now = new Date()): string {
  return `${now.getFullYear()}-${now.getMonth() + 1}-${now.getDate()}`;
}

function publish(today: Today) {
  known = { day: localDay(), at: Date.now(), today };
  for (const listener of listeners) listener();
}

/** Asks again whether today's conversation exists and has begun. */
export function checkToday(): Promise<void> {
  checking ??= (async () => {
    try {
      const conversation = await fetchToday();
      const started = conversation
        ? (await api<unknown[]>(`/conversations/${conversation.id}/messages`)).length > 0
        : false;
      publish({ conversation, started });
    } catch {
      // Unknown: the pet wears no clip rather than promise an opening.
    } finally {
      checking = null;
    }
  })();
  return checking;
}

/** Today's conversation has begun (an opening or the learner's first message). */
export function noteTodayStarted(conversation: Conversation) {
  publish({ conversation, started: true });
}

/** Forgets what was found (tests). */
export function resetToday() {
  known = null;
  checking = null;
}

/**
 * Today's conversation as last found, looked up while `on`: at first, on another day, and
 * on focus once stale. undefined while unknown.
 */
export function useToday(on: boolean): Today | undefined {
  const today = useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    () => (known && known.day === localDay() ? known.today : undefined),
    () => undefined,
  );
  useEffect(() => {
    if (!on) return;
    if (!known || known.day !== localDay()) void checkToday();
    const onFocus = () => {
      if (!known || known.day !== localDay() || Date.now() - known.at > STALE_MS) void checkToday();
    };
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, [on]);
  return on ? today : undefined;
}

/**
 * Whether opening the pet now would have the tutor open today's conversation (ADR 0041):
 * the switch is on, a chat model is set up, and nothing has been said today yet. The pet
 * wears its AI hair clip while this holds.
 */
export function openingDue(
  dailyOpening: boolean | undefined,
  modelReady: boolean | undefined,
  today: Today | undefined,
): boolean {
  return dailyOpening !== false && modelReady === true && today !== undefined && !today.started;
}
