import { useCallback, useSyncExternalStore } from "react";

import { api, apiFetch, ApiError } from "@/lib/api";
import { isOnline, pickVoices, type VoiceChoice, type VoiceLike } from "@/lib/voices";

/**
 * Read-aloud (ADR 0018, ADR 0028 §3). When the tenant has a read-aloud route, the server
 * reads the languages it has a voice for; everything else, and everything once the server
 * fails on this page, is read in the browser: free, no model, no server. Browser voices
 * vary by device, so we pick the best one this device has for each language.
 */
export const canSpeak = () => typeof window !== "undefined" && "speechSynthesis" in window;

export type SpeechLang = "zh-CN" | "en-US";
export type Segment = { text: string; lang: SpeechLang };
// A word is asked of the server at speed 1, the speed its pronunciation was generated
// ahead of time in, and played at the learner's speed (Q55a).
type Piece = Segment & { word?: boolean };

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

/**
 * Read-aloud settings (ADR 0018 §2): kept in this browser, as voices differ by device.
 * `server` off reads everything with this device's voices (Q54a).
 */
export type SpeechSettings = VoiceChoice & { enRate: number; server: boolean };

export const EN_RATE_MIN = 0.6;
export const EN_RATE_MAX = 1.2;

export const DEFAULT_SPEECH_SETTINGS: SpeechSettings = {
  accent: "en-US",
  enRate: 0.9,
  enVoice: null,
  zhVoice: null,
  server: true,
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
  /** Which language the text is in, whatever voice reads it. */
  kind: SpeechLang;
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
  settings: SpeechSettings & { failed?: ReadonlySet<string> },
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
    for (const text of splitSentences(segment.text)) {
      utterances.push({ text, kind: segment.lang, lang, voice, rate });
    }
  }
  return { utterances, skipped: [...skipped] };
}

/**
 * `queue` with each failed voice swapped for the best one left for its language (ADR 0018
 * §1); pieces with no voice left are dropped, and `skipped` says which language.
 */
export function revoice<V extends VoiceLike>(
  queue: Utterance<V>[],
  voices: readonly V[],
  settings: SpeechSettings & { failed: ReadonlySet<string> },
): { utterances: Utterance<V>[]; skipped: SpeechLang[] } {
  const picked = pickVoices(voices, settings);
  const skipped = new Set<SpeechLang>();
  const utterances: Utterance<V>[] = [];
  for (const item of queue) {
    if (!item.voice || !settings.failed.has(item.voice.voiceURI)) {
      utterances.push(item);
      continue;
    }
    const english = item.kind === "en-US";
    const voice = english ? picked.en : picked.zh;
    if (!voice) skipped.add(item.kind);
    else utterances.push({ ...item, voice, lang: english ? voice.lang : "zh-CN" });
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
    server: stored.server !== false,
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

/** Reads a short sample in `lang` with this device's voices, to try one. */
export function speakSample(lang: SpeechLang): SpeechLang[] {
  if (!canSpeak()) return [];
  const plan = planSpeech([{ text: SAMPLES[lang], lang }], browserVoices(), {
    ...currentSettings(),
    failed: failedVoices,
  });
  read(`sample-${lang}`, [], plan.utterances);
  return plan.skipped;
}

// What is being read now, by whoever asked (one message at a time), for the stop button.
let speaking: string | null = null;
const listeners = new Set<() => void>();
function setSpeaking(owner: string | null) {
  speaking = owner;
  listeners.forEach((listener) => listener());
}

// Voices that made no sound on this page (Q25g: for this page only, so a network that
// comes back gets them back on reload), and whose reading fell back first, for its notice.
let failedVoices: ReadonlySet<string> = new Set();
let fallbackOwner: string | null = null;
const failedListeners = new Set<() => void>();

function markFailed(voice: VoiceLike, owner: string | null) {
  failedVoices = new Set([...failedVoices, voice.voiceURI]);
  fallbackOwner ??= owner;
  failedListeners.forEach((listener) => listener());
}

function subscribeFailed(listener: () => void) {
  failedListeners.add(listener);
  return () => failedListeners.delete(listener);
}

/** Voices (`voiceURI`) that made no sound on this page. */
export function useFailedVoices(): ReadonlySet<string> {
  return useSyncExternalStore(
    subscribeFailed,
    () => failedVoices,
    () => failedVoices,
  );
}

/** Whether `owner`'s reading was the first on this page to fall back to another voice. */
export function useFellBack(owner: string): boolean {
  return useSyncExternalStore(
    subscribeFailed,
    () => fallbackOwner === owner,
    () => false,
  );
}

/** The languages `POST /speech/tts` takes: English in either accent, and Chinese. */
export type ServerLang = "en-US" | "en-GB" | "zh-CN";

/**
 * Server read-aloud as this page knows it: the languages the tenant's route has a voice
 * for (null until asked), and whether it failed here. A failure holds for this page only,
 * like a silent browser voice: a reload asks again.
 */
export type ServerSpeech = {
  languages: ReadonlySet<ServerLang> | null;
  down: boolean;
  noVoice: ReadonlySet<ServerLang>;
  /** How shadowing is scored (ADR 0028 §5); null until asked, or with nothing to score it. */
  shadowing: ShadowingMode | null;
  /** Voice messages are transcribed (task 59): null until asked. */
  asr: boolean | null;
};

/** Scored by pronunciation assessment, or only compared with a transcript. */
export type ShadowingMode = "assessment" | "rough";

let server: ServerSpeech = {
  languages: null,
  down: false,
  noVoice: new Set(),
  shadowing: null,
  asr: null,
};
let capabilitiesLoad: Promise<void> | null = null;
const serverListeners = new Set<() => void>();

function setServer(change: Partial<ServerSpeech>) {
  server = { ...server, ...change };
  serverListeners.forEach((listener) => listener());
}

function subscribeServer(listener: () => void) {
  serverListeners.add(listener);
  return () => serverListeners.delete(listener);
}

type Capabilities = {
  tts: boolean;
  tts_languages: ServerLang[];
  shadowing?: ShadowingMode | null;
  asr?: boolean;
};

/**
 * Asks the backend once per page which languages it reads, how it scores shadowing and
 * whether it transcribes; any error means none of them. Until it has answered, the
 * browser reads everything.
 */
export function loadCapabilities(): Promise<void> {
  capabilitiesLoad ??= Promise.resolve()
    .then(() => api<Capabilities>("/speech/capabilities"))
    .then(
      (caps): Partial<ServerSpeech> => ({
        languages: new Set(caps.tts ? caps.tts_languages : []),
        shadowing: caps.shadowing ?? null,
        asr: caps.asr ?? false,
      }),
    )
    .catch((): Partial<ServerSpeech> => ({ languages: new Set(), shadowing: null, asr: false }))
    .then(setServer);
  return capabilitiesLoad;
}

/** Server read-aloud on this page (asks the backend the first time). */
export function useServerSpeech(): ServerSpeech {
  return useSyncExternalStore(
    (listener) => {
      void loadCapabilities();
      return subscribeServer(listener);
    },
    () => server,
    () => server,
  );
}

const serverLang = (kind: SpeechLang, settings: SpeechSettings): ServerLang =>
  kind === "en-US" ? settings.accent : "zh-CN";

/** Whether the server reads `kind` now, with these settings. */
function serverReads(kind: SpeechLang, settings: SpeechSettings): boolean {
  const lang = serverLang(kind, settings);
  return (
    settings.server &&
    !server.down &&
    !server.noVoice.has(lang) &&
    (server.languages?.has(lang) ?? false)
  );
}

// The server's audio for a sentence that hasn't come this long after asking is taken as
// lost (ADR 0028 §3), and the browser reads from there on.
export const SERVER_START_TIMEOUT_MS = 4000;

/**
 * The server's audio for one sentence, or null after marking what failed: the language
 * when the route has no voice for it, the server (for this page) on anything else.
 */
async function fetchSpeech(piece: Piece, stop: AbortSignal): Promise<Blob | null> {
  const settings = currentSettings();
  const language = serverLang(piece.lang, settings);
  const request = new AbortController();
  const abort = () => request.abort();
  stop.addEventListener("abort", abort);
  const timer = setTimeout(abort, SERVER_START_TIMEOUT_MS);
  try {
    const response = await apiFetch("/speech/tts", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        text: piece.text,
        language,
        speed: piece.word ? 1 : piece.lang === "en-US" ? settings.enRate : ZH_RATE,
      }),
      signal: request.signal,
    });
    clearTimeout(timer);
    const audio = await response.blob();
    if (audio.size > 0) return audio;
    setServer({ down: true });
  } catch (error) {
    if (stop.aborted) return null; // stopped: nothing failed
    if (error instanceof ApiError && error.code === "no_tts_voice") {
      setServer({ noVoice: new Set([...server.noVoice, language]) });
    } else {
      setServer({ down: true });
    }
  } finally {
    clearTimeout(timer);
    stop.removeEventListener("abort", abort);
  }
  return null;
}

// One audio element for all the server's sentences. Safari plays audio only from an
// element that first played inside a click, so each reading starts it on a moment of
// silence right away, before any sentence has come back.
let player: HTMLAudioElement | null = null;
const SILENCE =
  "data:audio/wav;base64,UklGRnQAAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YVAAAACAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgA==";

function unlockPlayer() {
  player ??= new Audio();
  player.src = SILENCE;
  player.play()?.catch(() => {}); // refused here: refused later too, and caught there
}

// How to drop the sentence playing now when cut off.
let stopAudio: (() => void) | null = null;

/**
 * Plays `audio` at `rate` (pitch kept); true once it ends, false if it can't be played
 * (or is cut off).
 */
function playAudio(audio: Blob, rate = 1): Promise<boolean> {
  return new Promise((resolve) => {
    const url = URL.createObjectURL(audio);
    const element = (player ??= new Audio());
    const end = (ok: boolean) => {
      if (stopAudio !== drop) return;
      stopAudio = null;
      element.onended = element.onerror = null;
      URL.revokeObjectURL(url);
      resolve(ok);
    };
    const drop = () => {
      element.pause();
      end(false);
    };
    stopAudio = drop;
    element.onended = () => end(true);
    element.onerror = () => end(false);
    // Loading a source resets playbackRate to the default rate, so set both.
    element.defaultPlaybackRate = element.playbackRate = rate;
    element.src = url;
    Promise.resolve(element.play()).catch(() => end(false));
  });
}

function toUtterance({ text, lang, voice, rate }: Utterance<SpeechSynthesisVoice>) {
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = lang;
  if (voice) utterance.voice = voice;
  utterance.rate = rate;
  return utterance;
}

// An online voice that hasn't started this long after its turn came is taken as silent.
export const ONLINE_START_TIMEOUT_MS = 3000;

// Each browser run (and each restart after a fallback) has its own number; events from
// one that was cut off are ignored.
let session = 0;

/**
 * Queues `queue` with the browser's voices for `owner` and watches it piece by piece: an
 * online voice that errs, ends without starting, or doesn't start in time is marked
 * failed, and the rest is read again from that piece with the voices left. `onDone` runs
 * once the last piece is read.
 */
function play(
  owner: string | null,
  queue: Utterance<SpeechSynthesisVoice>[],
  onDone: () => void,
) {
  const id = ++session;
  window.speechSynthesis.cancel();
  if (queue.length === 0) return onDone();

  let timer: ReturnType<typeof setTimeout> | undefined;
  const started = queue.map(() => false);
  const live = () => id === session;
  const watch = (i: number) => {
    clearTimeout(timer);
    const voice = queue[i].voice;
    if (voice && isOnline(voice)) timer = setTimeout(() => fail(i), ONLINE_START_TIMEOUT_MS);
  };
  const fail = (i: number) => {
    if (!live()) return;
    clearTimeout(timer);
    markFailed(queue[i].voice!, owner);
    const rest = revoice(queue.slice(i), browserVoices(), {
      ...currentSettings(),
      failed: failedVoices,
    });
    play(owner, rest.utterances, onDone);
  };
  const done = (i: number) => {
    if (i + 1 < queue.length) return watch(i + 1);
    clearTimeout(timer);
    onDone();
  };
  const silent = (i: number) => {
    const voice = queue[i].voice;
    return !started[i] && voice !== null && isOnline(voice);
  };

  queue.forEach((item, i) => {
    const utterance = toUtterance(item);
    utterance.onstart = () => {
      if (!live()) return;
      started[i] = true;
      clearTimeout(timer);
    };
    utterance.onend = () => {
      if (live()) (silent(i) ? fail : done)(i);
    };
    utterance.onerror = (event) => {
      // Cut off by `cancel()`: a new reading, or the stop button.
      if (!live() || event.error === "interrupted" || event.error === "canceled") return;
      (silent(i) ? fail : done)(i);
    };
    window.speechSynthesis.speak(utterance);
  });
  watch(0);
}

// Each reading has its own number, and a signal that stops its requests.
let reading = 0;
let stopRequests: AbortController | null = null;

function cutOff() {
  reading++;
  session++; // events from what the browser was reading no longer count
  stopRequests?.abort();
  stopRequests = null;
  stopAudio?.();
  if (canSpeak()) window.speechSynthesis.cancel();
}

/**
 * Reads `pieces` (one sentence each) for `owner`, cutting off whatever was being read:
 * each by the server when it reads that language, else by the browser. While one sentence
 * plays the next is fetched. A sentence the server fails on is read again by the browser,
 * and so is the rest (or the rest in that language, when the route has no voice for it).
 * `browser` is read in the browser first, for a voice sample; with `feed`, more pieces
 * are added to `pieces` as they come. Returns whether this reading is still the current one.
 */
function read(
  owner: string | null,
  pieces: Piece[],
  browser: Utterance<SpeechSynthesisVoice>[] = [],
  feed?: Feed,
) {
  cutOff();
  const id = reading;
  const controller = new AbortController();
  stopRequests = controller;
  const live = () => id === reading;
  if (pieces.length === 0 && browser.length === 0 && !feed) {
    setSpeaking(null);
    return live;
  }
  setSpeaking(owner);

  const fetched = new Map<number, Promise<Blob | null>>();
  const fetchAt = (i: number) => {
    let audio = fetched.get(i);
    if (!audio) fetched.set(i, (audio = fetchSpeech(pieces[i], controller.signal)));
    return audio;
  };

  // Synchronous until a sentence goes to the server, so the browser's first sentence is
  // queued inside the click (Safari reads aloud only from one). Until the backend has said
  // what it reads (asked when a read-aloud button shows), the browser reads everything.
  const step = (i: number): void => {
    if (!live()) return;
    if (i >= pieces.length) {
      if (feed?.open) return void (feed.resume = () => step(i));
      return setSpeaking(null);
    }
    const settings = currentSettings();
    if (!serverReads(pieces[i].lang, settings)) {
      let end = i;
      while (end < pieces.length && !serverReads(pieces[end].lang, settings)) end++;
      if (!canSpeak()) return step(end);
      const plan = planSpeech(pieces.slice(i, end), browserVoices(), {
        ...settings,
        failed: failedVoices,
      });
      return play(owner, plan.utterances, () => step(end));
    }
    void fetchAt(i).then(async (audio) => {
      if (!live()) return;
      if (!audio) return step(i); // what failed is marked: the browser reads it
      const next = i + 1;
      if (next < pieces.length && serverReads(pieces[next].lang, currentSettings())) {
        void fetchAt(next);
      }
      const rate = pieces[i].word ? currentSettings().enRate : 1;
      if (await playAudio(audio, rate)) return step(next);
      if (!live()) return;
      setServer({ down: true }); // the page can't play it (blocked, or not audio)
      step(i);
    });
  };

  const settings = currentSettings();
  const english = feed !== undefined && serverReads("en-US", settings);
  if (english || pieces.some((piece) => serverReads(piece.lang, settings))) unlockPlayer();
  if (browser.length) play(owner, browser, () => step(0));
  else step(0);
  return live;
}

/**
 * A reading still being written: `resume` picks it up where it waits for the next
 * sentence, and once `open` is false it ends after the last one.
 */
type Feed = { open: boolean; resume: (() => void) | null };

// What a sentence end looks like in text still coming: a full stop only before a space,
// as in `splitSentences`, so a stop at the very end waits for what follows it.
const SENTENCE_END = /[。？！；;\n]|[.?!](?=\s)/gu;

/**
 * `text` cut after its last sentence end: the sentences that are complete, and the rest
 * still being written.
 */
export function takeSentences(text: string): [complete: string, rest: string] {
  let cut = 0;
  for (const match of text.matchAll(SENTENCE_END)) cut = match.index + match[0].length;
  return [text.slice(0, cut), text.slice(cut)];
}

// Markdown marks that would be read out: emphasis, code, headings, quotes, list bullets,
// and a link's address (its text is kept).
const plain = (markdown: string) =>
  markdown
    .replace(/\[([^\]]*)\]\([^)]*\)/g, "$1")
    .replace(/^\s*(?:#+|>|[-*+]|\d+\.)\s+/gm, "")
    .replace(/[*_`~]+/g, "");

export type SpeechStream = {
  /** More of the reply: each sentence is read once it is complete. */
  push(text: string): void;
  /** The reply is complete: what is left is read, then the reading ends. */
  end(): void;
};

/**
 * Reads a reply for `owner` while it streams in (task 59.1), cutting off whatever was
 * being read: sentences are read one after another as they complete, by the server or
 * the browser as `speakSegments` does. Start it inside the click that sent the message,
 * so Safari lets it play. Stopping (`stopSpeaking`, or any other reading) drops it; what
 * is pushed after that is ignored.
 */
export function speakStream(owner: string): SpeechStream {
  const pieces: Piece[] = [];
  const feed: Feed = { open: true, resume: null };
  const live = read(owner, pieces, [], feed);
  let rest = "";
  const add = (text: string) => {
    pieces.push(...sentences(speechSegments(plain(text))));
    const resume = feed.resume;
    feed.resume = null;
    resume?.();
  };
  return {
    push(text) {
      if (!live() || !feed.open) return;
      const [complete, more] = takeSentences(rest + text);
      rest = more;
      if (complete) add(complete);
    },
    end() {
      if (!live() || !feed.open) return;
      feed.open = false;
      add(rest);
      rest = "";
    },
  };
}

/**
 * Lets the server's audio play later: call it inside a click when what will be read comes
 * only after a wait (a voice message is transcribed before the reply streams), as Safari
 * plays audio only from an element that first played inside one.
 */
export function unlockSpeech() {
  if (serverReads("en-US", currentSettings())) unlockPlayer();
}

/** `segments` cut into sentences, each read on its own (by the server or the browser). */
const sentences = (segments: Segment[]): Segment[] =>
  segments.flatMap((segment) =>
    splitSentences(segment.text).map((text) => ({ text, lang: segment.lang })),
  );

/** Reads English `text` (a word, a sentence) aloud, cutting off whatever was being read. */
export function speak(text: string) {
  read(null, sentences([{ text, lang: "en-US" }]));
}

/**
 * Reads the segments one after another for `owner`, cutting off whatever was being read.
 * Returns the languages left out for want of a voice: neither the server reads them nor
 * does this device have one.
 */
export function speakSegments(owner: string, segments: Segment[]): SpeechLang[] {
  const pieces = sentences(segments);
  read(owner, pieces);
  const settings = currentSettings();
  const browserOnly = pieces.filter((piece) => !serverReads(piece.lang, settings));
  if (!canSpeak()) return [...new Set(browserOnly.map((piece) => piece.lang))];
  return planSpeech(browserOnly, browserVoices(), { ...settings, failed: failedVoices }).skipped;
}

/**
 * Reads an English word (or phrase) aloud, cutting off whatever was being read. The
 * server's audio is the one generated ahead of time when there is one (ADR 0028 §4).
 */
export function speakWord(word: string) {
  read(null, [{ text: word.trim(), lang: "en-US", word: true }]);
}

export function stopSpeaking() {
  cutOff();
  setSpeaking(null);
}

/**
 * Whether there is anything to read English with: the server, or a browser English voice.
 * False during server rendering, and once the browser has listed its voices, none of them
 * is English and the server doesn't read English.
 */
export function useCanSpeak(): boolean {
  return useSyncExternalStore(
    (listener) => {
      void loadCapabilities();
      const unsubscribers = [
        subscribeVoices(listener),
        subscribeSettings(listener),
        subscribeFailed(listener),
        subscribeServer(listener),
      ];
      return () => unsubscribers.forEach((unsubscribe) => unsubscribe());
    },
    () => {
      const settings = currentSettings();
      if (serverReads("en-US", settings)) return true;
      if (!canSpeak()) return false;
      const list = browserVoices();
      return list.length === 0 || pickVoices(list, { ...settings, failed: failedVoices }).en !== null;
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
