import { useCallback, useSyncExternalStore } from "react";

/**
 * Per-browser display preferences. Only for what changes how things look: storage can
 * be unavailable (private mode, blocked site data), and then the default applies.
 */
const SHOW_ACTIVITY_KEY = "lingo.showAgentActivity";
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

/** Whether replies show what the tutor did (ADR 0013 §3). Hiding changes display only. */
export function useShowActivity(): [boolean, (show: boolean) => void] {
  const show = useSyncExternalStore(
    subscribe,
    () => read(SHOW_ACTIVITY_KEY) !== "false",
    () => true,
  );
  const set = useCallback((value: boolean) => {
    fallback.set(SHOW_ACTIVITY_KEY, String(value));
    try {
      window.localStorage.setItem(SHOW_ACTIVITY_KEY, String(value));
    } catch {
      // Not saved; it still applies until the page is reloaded.
    }
    window.dispatchEvent(new Event(CHANGE_EVENT));
  }, []);
  return [show, set];
}
