import { useEffect, useSyncExternalStore } from "react";

import type { AvatarState } from "@/components/tutor/avatar-state";
import { JOY_MS } from "@/components/tutor/avatar-state";
import { subscribeVoiceActive, voiceActive } from "@/lib/voice-level";

/**
 * What the desk pet reacts to (ADR 0032 §4a). Pages only tell this bus what happens (a
 * recording, a wait for the tutor's reply, a right answer); they know nothing of the pet,
 * and nothing here needs one to be on the page.
 *
 * The pet's state, strongest first: listening (recording), speaking (the tutor's voice
 * playing), thinking (waiting on the reply), happy (one hop), sleeping (left alone for
 * `SLEEP_AFTER_MS`), else idle.
 */

/** No keys, pointer, touch or scrolling for this long: the pet dozes off (Q66o). */
export const SLEEP_AFTER_MS = 3 * 60_000;
/** How often an idle page checks whether it is time to doze. */
const SLEEP_CHECK_MS = 10_000;

type Hold = "listening" | "thinking";

const holds: Record<Hold, number> = { listening: 0, thinking: 0 };
let happy = false;
let happyTimer: ReturnType<typeof setTimeout> | undefined;
let asleep = false;
let lastActive = 0;
const listeners = new Set<() => void>();

function notify() {
  listeners.forEach((listener) => listener());
}

/**
 * Marks something going on until the returned function is called (once; more calls do
 * nothing): a recording (`listening`), or a wait for the tutor's first words (`thinking`).
 */
export function petHold(kind: Hold): () => void {
  holds[kind]++;
  wake();
  notify();
  let done = false;
  return () => {
    if (done) return;
    done = true;
    holds[kind]--;
    wake();
    notify();
  };
}

/** Holds `kind` while `active`, for as long as the calling component is there. */
export function usePetHold(kind: Hold, active: boolean) {
  useEffect(() => (active ? petHold(kind) : undefined), [kind, active]);
}

/**
 * Something went well (a right answer, a round of words, today's plan): one hop. One at
 * a time: what comes while a hop plays is dropped, so it never hops on and on (Q66p).
 */
export function petHappy() {
  wake();
  if (happy) return;
  happy = true;
  notify();
  happyTimer = setTimeout(() => {
    happy = false;
    notify();
  }, JOY_MS);
}

const CHEERED_KEY = "lingo.tutorPet.cheeredDay";
const PLAN_DONE_EVENT = "lingo:pet-plan-done";

/**
 * Today's plan is done (Q66p): a hop the first time this device sees it on `day`, not on
 * every visit to the dashboard after.
 */
export function petPlanDone(day: string) {
  try {
    if (window.localStorage.getItem(CHEERED_KEY) === day) return;
    window.localStorage.setItem(CHEERED_KEY, day);
  } catch {
    // Not remembered: it may hop again on the next visit, which is harmless.
  }
  petHappy();
  window.dispatchEvent(new Event(PLAN_DONE_EVENT));
}

/** Runs `then` when today's plan is first seen done (the pet's cheer, ADR 0039 §4). */
export function useOnPlanDone(then: () => void) {
  useEffect(() => {
    window.addEventListener(PLAN_DONE_EVENT, then);
    return () => window.removeEventListener(PLAN_DONE_EVENT, then);
  }, [then]);
}

/** The learner did something: an asleep pet wakes, and dozing waits from now. */
export function petActivity(now = Date.now()) {
  lastActive = now;
  wake();
}

function wake() {
  if (!asleep) return;
  asleep = false;
  notify();
}

/** The pet's state now. */
export function petState(): AvatarState {
  if (holds.listening > 0) return "listening";
  if (voiceActive()) return "speaking";
  if (holds.thinking > 0) return "thinking";
  if (happy) return "happy";
  return asleep ? "sleeping" : "idle";
}

/** Dozes off once idle for long enough; called on a timer while a pet watches. */
export function checkSleep(now = Date.now()) {
  if (petState() !== "idle") {
    lastActive = now; // talking, listening, hopping: not left alone
    return;
  }
  if (now - lastActive >= SLEEP_AFTER_MS) {
    asleep = true;
    notify();
  }
}

const ACTIVITY = ["pointerdown", "pointermove", "keydown", "wheel", "touchstart", "scroll"];

// While a pet watches: the learner's activity, the voice, and a timer for dozing.
let watching = 0;
let stopWatching: (() => void) | null = null;

function startWatching() {
  lastActive = Date.now();
  // Many events a second while the mouse moves: only the time is noted.
  const onActivity = () => petActivity();
  for (const type of ACTIVITY) {
    window.addEventListener(type, onActivity, { capture: true, passive: true });
  }
  const unsubscribeVoice = subscribeVoiceActive(notify);
  const timer = setInterval(() => checkSleep(), SLEEP_CHECK_MS);
  stopWatching = () => {
    for (const type of ACTIVITY) window.removeEventListener(type, onActivity, { capture: true });
    unsubscribeVoice();
    clearInterval(timer);
  };
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  if (watching++ === 0) startWatching();
  return () => {
    listeners.delete(listener);
    if (--watching === 0) {
      stopWatching?.();
      stopWatching = null;
    }
  };
}

/** The pet's state, kept up to date. */
export function usePetState(): AvatarState {
  return useSyncExternalStore(subscribe, petState, () => "idle");
}

/** Back to nothing going on (tests). */
export function resetPet() {
  holds.listening = holds.thinking = 0;
  clearTimeout(happyTimer);
  happy = asleep = false;
  lastActive = Date.now();
}
