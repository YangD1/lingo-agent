import { useSyncExternalStore } from "react";

/** Read-aloud in the browser (ADR 0017 §5): free, no model, no server; voices vary by device. */
export const canSpeak = () => typeof window !== "undefined" && "speechSynthesis" in window;

export type SpeechLang = "zh-CN" | "en-US";
export type Segment = { text: string; lang: SpeechLang };

// Han characters, CJK punctuation and full-width forms read as Chinese; Latin letters as English.
const HAN = /[　-〿㐀-䶿一-鿿豈-﫿＀-￯]/;
const LATIN = /[A-Za-z]/;

/**
 * `text` cut into runs of Chinese and English, each to be read with its own voice. Digits,
 * spaces and ASCII punctuation stay with the run they're in.
 */
export function speechSegments(text: string): Segment[] {
  const out: Segment[] = [];
  let lang: SpeechLang | null = null;
  let run = "";
  for (const ch of text) {
    const of: SpeechLang | null = HAN.test(ch) ? "zh-CN" : LATIN.test(ch) ? "en-US" : null;
    if (of && lang && of !== lang) {
      out.push({ text: run, lang });
      run = "";
    }
    if (of) lang = of;
    run += ch;
  }
  if (lang) out.push({ text: run, lang });
  return out.map((s) => ({ ...s, text: s.text.trim() })).filter((s) => s.text);
}

// What is being read now, by whoever asked (one message at a time), for the stop button.
let speaking: string | null = null;
const listeners = new Set<() => void>();
function setSpeaking(owner: string | null) {
  speaking = owner;
  listeners.forEach((listener) => listener());
}

/** Reads `text` aloud, cutting off whatever was being read. */
export function speak(text: string, lang: SpeechLang = "en-US") {
  if (!canSpeak()) return;
  window.speechSynthesis.cancel();
  setSpeaking(null);
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = lang;
  window.speechSynthesis.speak(utterance);
}

/** Reads the segments one after another for `owner`, cutting off whatever was being read. */
export function speakSegments(owner: string, segments: Segment[]) {
  if (!canSpeak() || segments.length === 0) return;
  window.speechSynthesis.cancel();
  const utterances = segments.map((segment) => {
    const utterance = new SpeechSynthesisUtterance(segment.text);
    utterance.lang = segment.lang;
    return utterance;
  });
  const last = utterances[utterances.length - 1];
  last.onend = last.onerror = () => {
    if (speaking === owner) setSpeaking(null);
  };
  setSpeaking(owner);
  utterances.forEach((utterance) => window.speechSynthesis.speak(utterance));
}

export function stopSpeaking() {
  if (canSpeak()) window.speechSynthesis.cancel();
  setSpeaking(null);
}

/** False during server rendering, so the button appears only once the browser can read. */
export function useCanSpeak(): boolean {
  return useSyncExternalStore(
    () => () => {},
    canSpeak,
    () => false,
  );
}

/** Whether `owner`'s text is being read now. */
export function useSpeaking(owner: string): boolean {
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    () => speaking === owner,
    () => false,
  );
}
