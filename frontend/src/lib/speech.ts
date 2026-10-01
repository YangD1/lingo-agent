import { useCallback, useSyncExternalStore } from "react";

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

/** Read-aloud settings (ADR 0018 §2): kept in this browser, as voices differ by device. */
export type SpeechSettings = VoiceChoice & { enRate: number };

export const EN_RATE_MIN = 0.6;
export const EN_RATE_MAX = 1.2;

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
// One empty list, so a snapshot without voices is the same each time.
const NO_VOICES: SpeechSynthesisVoice[] = [];
let voices = NO_VOICES;
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
  if (!canSpeak()) return NO_VOICES;
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

const SETTINGS_KEY = "lingo.speech";
const SETTINGS_EVENT = "lingo:speech";
// What this page set, for when storage is unavailable (private mode, blocked site data).
let settingsFallback: string | null = null;
let settingsCache: { raw: string | null; settings: SpeechSettings } | null = null;

/** Stored settings, anything missing or out of range back to its default. */
export function parseSpeechSettings(raw: string | null): SpeechSettings {
  let stored: Record<string, unknown> = {};
  try {
    const parsed: unknown = raw ? JSON.parse(raw) : {};
    if (parsed && typeof parsed === "object") stored = parsed as Record<string, unknown>;
  } catch {
    // Unreadable: defaults.
  }
  const text = (value: unknown) => (typeof value === "string" && value ? value : null);
  const rate = typeof stored.enRate === "number" ? stored.enRate : NaN;
  return {
    accent: stored.accent === "en-GB" ? "en-GB" : "en-US",
    enRate: Number.isFinite(rate)
      ? Math.min(EN_RATE_MAX, Math.max(EN_RATE_MIN, rate))
      : DEFAULT_SPEECH_SETTINGS.enRate,
    enVoice: text(stored.enVoice),
    zhVoice: text(stored.zhVoice),
  };
}

/** The settings in use; the same object while they haven't changed. */
function currentSettings(): SpeechSettings {
  let raw: string | null;
  try {
    raw = window.localStorage.getItem(SETTINGS_KEY);
  } catch {
    raw = settingsFallback; // storage unavailable: what this page set, if anything
  }
  if (settingsCache?.raw !== raw) settingsCache = { raw, settings: parseSpeechSettings(raw) };
  return settingsCache.settings;
}

function saveSettings(settings: SpeechSettings) {
  const raw = JSON.stringify(settings);
  settingsFallback = raw;
  try {
    window.localStorage.setItem(SETTINGS_KEY, raw);
  } catch {
    // Not saved; it still applies until the page is reloaded.
  }
  window.dispatchEvent(new Event(SETTINGS_EVENT));
}

function subscribeSettings(onChange: () => void) {
  window.addEventListener("storage", onChange); // other tabs
  window.addEventListener(SETTINGS_EVENT, onChange); // this tab
  return () => {
    window.removeEventListener("storage", onChange);
    window.removeEventListener(SETTINGS_EVENT, onChange);
  };
}

/** The read-aloud settings, and a setter taking the fields to change. */
export function useSpeechSettings(): [SpeechSettings, (change: Partial<SpeechSettings>) => void] {
  const settings = useSyncExternalStore(
    subscribeSettings,
    currentSettings,
    () => DEFAULT_SPEECH_SETTINGS,
  );
  const update = useCallback(
    (change: Partial<SpeechSettings>) => saveSettings({ ...currentSettings(), ...change }),
    [],
  );
  return [settings, update];
}

/** The voices this browser has listed so far (none during server rendering). */
export function useVoices(): SpeechSynthesisVoice[] {
  return useSyncExternalStore(subscribeVoices, browserVoices, () => NO_VOICES);
}

const SAMPLES: Record<SpeechLang, string> = {
  "en-US": "Hello! It's nice to meet you. Shall we practise some English today?",
  "zh-CN": "你好！很高兴认识你，今天我们一起练习英语吧。",
};

/** Reads a short sample in `lang` with the current settings, to try a voice. */
export function speakSample(lang: SpeechLang): SpeechLang[] {
  return speakSegments(`sample-${lang}`, [{ text: SAMPLES[lang], lang }]);
}

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
    (listener) => {
      const unsubscribeVoices = subscribeVoices(listener);
      const unsubscribeSettings = subscribeSettings(listener);
      return () => {
        unsubscribeVoices();
        unsubscribeSettings();
      };
    },
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
