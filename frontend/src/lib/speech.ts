import { useSyncExternalStore } from "react";

import { pickVoices, type VoiceChoice, type VoiceLike } from "@/lib/voices";

/**
 * Read-aloud in the browser (ADR 0017 §5, ADR 0018 §1): free, no model, no server. Voices
 * vary by device, so we pick the best one this device has for each language.
 */
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

/** Read-aloud settings (ADR 0018 §2); kept in this browser from task 25.3. */
export type SpeechSettings = VoiceChoice & { enRate: number };

export const DEFAULT_SPEECH_SETTINGS: SpeechSettings = {
  accent: "en-US",
  enRate: 0.9,
  enVoice: null,
  zhVoice: null,
};
const ZH_RATE = 1;

// Chrome's online voices stop reading about 15 seconds in, so long text goes in pieces.
const MAX_SENTENCE = 200;

/**
 * `text` cut after each sentence end (and line break); a sentence still longer than
 * `MAX_SENTENCE` is cut after its commas. A full stop counts only before a space, so
 * "3.5" stays whole.
 */
export function splitSentences(text: string): string[] {
  const sentences = text.split(/(?<=[。？！；;\n]|[.?!](?=\s))/u);
  return sentences
    .flatMap((sentence) =>
      sentence.length > MAX_SENTENCE ? sentence.split(/(?<=[,，、])/u) : [sentence],
    )
    .map((sentence) => sentence.trim())
    .filter((sentence) => /[\p{L}\p{N}]/u.test(sentence));
}

export type Utterance<V extends VoiceLike = VoiceLike> = {
  text: string;
  lang: string;
  /** Null when the browser hasn't listed its voices: it picks one for `lang` itself. */
  voice: V | null;
  rate: number;
};

/**
 * What to say, sentence by sentence, with which voice. With no voice list (not loaded, or
 * a browser that never lists them) each piece goes by language alone. With a list but no
 * voice for a language, that language is left out and `skipped` says which.
 */
export function planSpeech<V extends VoiceLike>(
  segments: Segment[],
  voices: readonly V[],
  settings: SpeechSettings,
): { utterances: Utterance<V>[]; skipped: SpeechLang[] } {
  const picked = voices.length ? pickVoices(voices, settings) : null;
  const skipped = new Set<SpeechLang>();
  const utterances: Utterance<V>[] = [];
  for (const segment of segments) {
    const english = segment.lang === "en-US";
    const voice = picked ? (english ? picked.en : picked.zh) : null;
    if (picked && !voice) {
      skipped.add(segment.lang);
      continue;
    }
    const rate = english ? settings.enRate : ZH_RATE;
    // A multilingual voice reading Chinese is told the text is Chinese.
    const lang = english ? (voice?.lang ?? settings.accent) : "zh-CN";
    for (const text of splitSentences(segment.text)) utterances.push({ text, lang, voice, rate });
  }
  return { utterances, skipped: [...skipped] };
}

// The browser's voices. Chrome lists them only after `voiceschanged`; Safari at once.
let voices: SpeechSynthesisVoice[] = [];
let voicesWatched = false;
const voiceListeners = new Set<() => void>();

/** The list as the browser has it now; kept as long as it hasn't changed. */
function currentVoices(): SpeechSynthesisVoice[] {
  const next = window.speechSynthesis.getVoices?.() ?? [];
  const same = next.length === voices.length && next.every((voice, i) => voice === voices[i]);
  if (!same) voices = next;
  return voices;
}

function browserVoices(): SpeechSynthesisVoice[] {
  if (!canSpeak()) return [];
  if (!voicesWatched) {
    voicesWatched = true;
    window.speechSynthesis.addEventListener?.("voiceschanged", () => {
      currentVoices();
      voiceListeners.forEach((listener) => listener());
    });
  }
  return currentVoices();
}

function subscribeVoices(listener: () => void) {
  voiceListeners.add(listener);
  return () => voiceListeners.delete(listener);
}

/** The settings in use; task 25.3 reads them from this browser. */
const currentSettings = (): SpeechSettings => DEFAULT_SPEECH_SETTINGS;

// What is being read now, by whoever asked (one message at a time), for the stop button.
let speaking: string | null = null;
const listeners = new Set<() => void>();
function setSpeaking(owner: string | null) {
  speaking = owner;
  listeners.forEach((listener) => listener());
}

function toUtterance({ text, lang, voice, rate }: Utterance<SpeechSynthesisVoice>) {
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = lang;
  if (voice) utterance.voice = voice;
  utterance.rate = rate;
  return utterance;
}

/** Reads English `text` (a word, a sentence) aloud, cutting off whatever was being read. */
export function speak(text: string) {
  if (!canSpeak()) return;
  window.speechSynthesis.cancel();
  setSpeaking(null);
  const plan = planSpeech([{ text, lang: "en-US" }], browserVoices(), currentSettings());
  plan.utterances.forEach((u) => window.speechSynthesis.speak(toUtterance(u)));
}

/**
 * Reads the segments one after another for `owner`, cutting off whatever was being read.
 * Returns the languages left out for want of a voice on this device.
 */
export function speakSegments(owner: string, segments: Segment[]): SpeechLang[] {
  if (!canSpeak() || segments.length === 0) return [];
  window.speechSynthesis.cancel();
  const plan = planSpeech(segments, browserVoices(), currentSettings());
  const utterances = plan.utterances.map(toUtterance);
  if (utterances.length === 0) {
    setSpeaking(null);
    return plan.skipped;
  }
  const last = utterances[utterances.length - 1];
  last.onend = last.onerror = () => {
    if (speaking === owner) setSpeaking(null);
  };
  setSpeaking(owner);
  utterances.forEach((utterance) => window.speechSynthesis.speak(utterance));
  return plan.skipped;
}

export function stopSpeaking() {
  if (canSpeak()) window.speechSynthesis.cancel();
  setSpeaking(null);
}

/**
 * Whether there is anything to read English with: false during server rendering, and
 * once the browser has listed its voices and none of them is English.
 */
export function useCanSpeak(): boolean {
  return useSyncExternalStore(
    subscribeVoices,
    () => {
      if (!canSpeak()) return false;
      const list = browserVoices();
      return list.length === 0 || pickVoices(list, currentSettings()).en !== null;
    },
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
