import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { VoiceLike } from "@/lib/voices";

// Reading with online voices that may make no sound (ADR 0018 §1, task 25.7). The module
// keeps what failed for the page, so each test loads it afresh.

const v = (name: string, lang: string, local: boolean): VoiceLike => ({
  name,
  lang,
  localService: local,
  default: false,
  voiceURI: name,
});
const ARIA = v("Microsoft Aria Online (Natural) - English (United States)", "en-US", false);
const ZIRA = v("Microsoft Zira - English (United States)", "en-US", true);
const XIAOXIAO = v("Microsoft Xiaoxiao Online (Natural) - Chinese (Mainland)", "zh-CN", false);
const HUIHUI = v("Microsoft Huihui - Chinese (Simplified, PRC)", "zh-CN", true);

type Fake = {
  text: string;
  voice: VoiceLike | null;
  onstart: (() => void) | null;
  onend: (() => void) | null;
  onerror: ((e: { error: string }) => void) | null;
};

let queued: Fake[];
let cancel: ReturnType<typeof vi.fn>;

async function load() {
  vi.resetModules();
  return import("@/lib/speech");
}

beforeEach(() => {
  vi.useFakeTimers();
  queued = [];
  cancel = vi.fn(() => {
    queued = [];
  });
  vi.stubGlobal("speechSynthesis", {
    getVoices: () => [ARIA, ZIRA, XIAOXIAO, HUIHUI],
    cancel,
    speak: (u: Fake) => queued.push(u),
  });
  vi.stubGlobal(
    "SpeechSynthesisUtterance",
    class {
      lang = "";
      voice: VoiceLike | null = null;
      rate = 1;
      onstart = null;
      onend = null;
      onerror = null;
      constructor(public text: string) {}
    },
  );
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

const segments = [
  { text: "Good job! Say it again.", lang: "en-US" as const },
  { text: "你说得对。", lang: "zh-CN" as const },
];
const read = () => queued.map((u) => [u.text, u.voice?.name]);

describe("online voices that make no sound", () => {
  it("falls back to a local voice when nothing starts within 3 seconds", async () => {
    const speech = await load();
    speech.speakSegments("m1", segments);
    expect(read()).toEqual([
      ["Good job!", ARIA.name],
      ["Say it again.", ARIA.name],
      ["你说得对。", XIAOXIAO.name],
    ]);

    vi.advanceTimersByTime(speech.ONLINE_START_TIMEOUT_MS);
    expect(read()).toEqual([
      ["Good job!", ZIRA.name],
      ["Say it again.", ZIRA.name],
      // Its own turn hasn't come yet: it gets its chance.
      ["你说得对。", XIAOXIAO.name],
    ]);
    // Zira is local: no clock on it.
    queued[0].onstart?.();
    queued[0].onend?.();
    queued[1].onstart?.();
    queued[1].onend?.();
    // Xiaoxiao's turn: it ends without ever starting, so it made no sound either.
    queued[2].onend?.();
    expect(read()).toEqual([["你说得对。", HUIHUI.name]]);
  });

  it("is remembered for the page: the next reading goes straight to the local voice", async () => {
    const speech = await load();
    speech.speakSegments("m1", segments.slice(0, 1));
    queued[0].onerror?.({ error: "network" });
    speech.speak("abandon");
    expect(read()).toEqual([["abandon", ZIRA.name]]);
  });

  it("keeps an online voice that started, however long it takes to finish", async () => {
    const speech = await load();
    speech.speakSegments("m1", segments.slice(0, 1));
    queued[0].onstart?.();
    vi.advanceTimersByTime(10_000);
    queued[0].onend?.();
    queued[1].onstart?.();
    vi.advanceTimersByTime(10_000);
    expect(read()).toEqual([
      ["Good job!", ARIA.name],
      ["Say it again.", ARIA.name],
    ]);
  });

  it("is not fooled by its own cancel, nor by the stop button", async () => {
    const speech = await load();
    speech.speakSegments("m1", segments.slice(0, 1));
    const first = queued[0];
    speech.stopSpeaking();
    first.onerror?.({ error: "interrupted" });
    vi.advanceTimersByTime(10_000);
    speech.speak("abandon");
    expect(read()).toEqual([["abandon", ARIA.name]]);
  });
});
