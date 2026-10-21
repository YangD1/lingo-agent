import { useCallback, useSyncExternalStore } from "react";

import { applyFont, FONT_KEY, type FontChoice, parseFontChoice } from "@/lib/font-choice";
import { REVIEW_CHOICES, type ReviewChoice } from "@/lib/vocab";

/**
 * Per-browser display preferences. Only for what changes how things look: storage can
 * be unavailable (private mode, blocked site data), and then the default applies.
 */
const SHOW_ACTIVITY_KEY = "lingo.showAgentActivity";
const SPEAKING_AUTO_READ_KEY = "lingo.speaking.autoRead";
const SPEAKING_HIDE_TEXT_KEY = "lingo.speaking.hideText";
const REVIEW_FORMAT_KEY = "lingo.vocab.reviewFormat";
const PET_PLACE_KEY = "lingo.tutorPet.place";
const CHANGE_EVENT = "lingo:preferences";
// What this page set, for when storage refuses it.
const fallback = new Map<string, string>();

function read(key: string): string | null {
  try {
    return window.localStorage.getItem(key) ?? fallback.get(key) ?? null;
  } catch {
    return fallback.get(key) ?? null;
  }
}

function subscribe(onChange: () => void): () => void {
  window.addEventListener("storage", onChange); // other tabs
  window.addEventListener(CHANGE_EVENT, onChange); // this tab
  return () => {
    window.removeEventListener("storage", onChange);
    window.removeEventListener(CHANGE_EVENT, onChange);
  };
}

function useStored(key: string): [string | null, (value: string) => void] {
  const value = useSyncExternalStore(
    subscribe,
    () => read(key),
    () => null,
  );
  const set = useCallback(
    (next: string) => {
      fallback.set(key, next);
      try {
        window.localStorage.setItem(key, next);
      } catch {
        // Not saved; it still applies until the page is reloaded.
      }
      window.dispatchEvent(new Event(CHANGE_EVENT));
    },
    [key],
  );
  return [value, set];
}

/** Whether replies show what the tutor did (ADR 0013 §3). Hiding changes display only. */
export function useShowActivity(): [boolean, (show: boolean) => void] {
  return useFlag(SHOW_ACTIVITY_KEY, true);
}

/** Whether the speaking page reads the tutor's replies aloud as they come (Q59f). */
export function useSpeakingAutoRead(): [boolean, (on: boolean) => void] {
  return useFlag(SPEAKING_AUTO_READ_KEY, true);
}

/** Whether the speaking page hides the tutor's text, for listening practice (Q59e). */
export function useSpeakingHideText(): [boolean, (hide: boolean) => void] {
  return useFlag(SPEAKING_HIDE_TEXT_KEY, false);
}

/** How review cards are shown: the word, its sound, spelling, or a mix (task 63, Q63a). */
export function useReviewChoice(): [ReviewChoice, (choice: ReviewChoice) => void] {
  const [value, set] = useStored(REVIEW_FORMAT_KEY);
  const choice = REVIEW_CHOICES.find((c) => c === value) ?? "recognize";
  return [choice, set];
}

/** The text font (ADR 0060). Changing it applies at once; the boot script reapplies it on load. */
export function useFontChoice(): [FontChoice, (choice: FontChoice) => void] {
  const [value, set] = useStored(FONT_KEY);
  const setChoice = useCallback(
    (choice: FontChoice) => {
      applyFont(choice);
      set(choice);
    },
    [set],
  );
  return [parseFontChoice(value), setChoice];
}

/**
 * Where the desk pet sits on this device (ADR 0032 §4a): against the left or right edge,
 * `bottom` CSS pixels above the window's bottom (the page keeps it on screen), or collapsed
 * to a small button there.
 */
export type PetPlace = { side: "left" | "right"; bottom: number; collapsed: boolean };

// The corner (task 73.6): pages leave room for it at the end of their scroll area, and on
// the chat page it rises above the input box by itself.
export const DEFAULT_PET_PLACE: PetPlace = { side: "right", bottom: 16, collapsed: false };

/** What is stored, or the default for anything missing or malformed. */
export function parsePetPlace(raw: string | null): PetPlace {
  try {
    const value: unknown = JSON.parse(raw ?? "null");
    if (typeof value !== "object" || value === null) return DEFAULT_PET_PLACE;
    const { side, bottom, collapsed } = value as Record<string, unknown>;
    return {
      side: side === "left" ? "left" : "right",
      bottom:
        typeof bottom === "number" && Number.isFinite(bottom) && bottom >= 0
          ? Math.round(bottom)
          : DEFAULT_PET_PLACE.bottom,
      collapsed: collapsed === true,
    };
  } catch {
    return DEFAULT_PET_PLACE;
  }
}

export function usePetPlace(): [PetPlace, (place: PetPlace) => void] {
  const [value, set] = useStored(PET_PLACE_KEY);
  const setPlace = useCallback((place: PetPlace) => set(JSON.stringify(place)), [set]);
  return [parsePetPlace(value), setPlace];
}

function useFlag(key: string, fallbackValue: boolean): [boolean, (on: boolean) => void] {
  const [value, set] = useStored(key);
  const setFlag = useCallback((on: boolean) => set(String(on)), [set]);
  return [value === null ? fallbackValue : value === "true", setFlag];
}
