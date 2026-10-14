import { useCallback, useEffect, useState } from "react";

import { type Advice, fetchAdvice } from "@/lib/advice";
import { useOnReviewed } from "@/lib/vocab";

/** Looked at again when the window regains focus, if older than this. */
const STALE_MS = 60_000;

/**
 * The learning engine's advice for the pet (ADR 0039 §4): whether a chat model is set up,
 * and what to suggest. Loaded while `on`, again after a flashcards round and when the
 * learner comes back to the window. Null until loaded, or when it can't be had.
 */
export function usePetAdvice(on: boolean): { advice: Advice | null; reload: () => void } {
  const [advice, setAdvice] = useState<Advice | null>(null);
  const [loadedAt, setLoadedAt] = useState(0);

  const reload = useCallback(() => {
    fetchAdvice().then(
      (found) => {
        setAdvice(found);
        setLoadedAt(Date.now());
      },
      () => {},
    );
  }, []);

  useEffect(() => {
    if (on) reload();
  }, [on, reload]);

  useOnReviewed(
    useCallback(() => {
      if (on) reload();
    }, [on, reload]),
  );

  useEffect(() => {
    if (!on) return;
    const onFocus = () => {
      if (Date.now() - loadedAt > STALE_MS) reload();
    };
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, [on, loadedAt, reload]);

  return { advice: on ? advice : null, reload };
}
