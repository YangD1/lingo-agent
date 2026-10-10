import { useCallback, useSyncExternalStore } from "react";

/**
 * Per-browser display preferences. Only for what changes how things look: storage can
 * be unavailable (private mode, blocked site data), and then the default applies.
 */
const SHOW_ACTIVITY_KEY = "lingo.showAgentActivity";
const SPEAKING_AUTO_READ_KEY = "lingo.speaking.autoRead";
const SPEAKING_HIDE_TEXT_KEY = "lingo.speaking.hideText";
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

function useFlag(key: string, fallbackValue: boolean): [boolean, (on: boolean) => void] {
  const [value, set] = useStored(key);
  const setFlag = useCallback((on: boolean) => set(String(on)), [set]);
  return [value === null ? fallbackValue : value === "true", setFlag];
}
