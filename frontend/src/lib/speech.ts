import { useSyncExternalStore } from "react";

/** Read-aloud in the browser (ADR 0017 §5): free, no model, no server; voices vary by device. */
export const canSpeak = () => typeof window !== "undefined" && "speechSynthesis" in window;

/** Reads `text` aloud, cutting off whatever was being read. */
export function speak(text: string, lang = "en-US") {
  if (!canSpeak()) return;
  window.speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = lang;
  window.speechSynthesis.speak(utterance);
}

/** False during server rendering, so the button appears only once the browser can read. */
export function useCanSpeak(): boolean {
  return useSyncExternalStore(
    () => () => {},
    canSpeak,
    () => false,
  );
}
