import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { VoiceLike } from "@/lib/voices";

// Server read-aloud first, the browser when it can't (ADR 0028 §3, task 54.1). The module
// keeps what the server reads and what failed for the page, so each test loads it afresh.

const v = (name: string, lang: string): VoiceLike => ({
  name,
  lang,
  localService: true,
  default: false,
  voiceURI: name,
});
const ZIRA = v("Microsoft Zira - English (United States)", "en-US");
const HUIHUI = v("Microsoft Huihui - Chinese (Simplified, PRC)", "zh-CN");

type Utterance = { text: string; onend: (() => void) | null };
type Player = {
  src: string;
  paused: boolean;
  playbackRate: number;
  onended: (() => void) | null;
  onerror: (() => void) | null;
};

let spoken: Utterance[];
let players: Player[];
let requests: { text: string; language: string; speed: number }[];
let respond: (body: { text: string; language: string }) => Response | Promise<Response>;

const audio = () => new Response(new Blob([new Uint8Array([1, 2, 3])], { type: "audio/mpeg" }));
const failure = (status: number, code: string) =>
  new Response(JSON.stringify({ detail: { code, message: code } }), { status });

function stubFetch(languages: string[]) {
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string, init: RequestInit = {}) => {
      if (url === "/api/speech/capabilities") {
        return Promise.resolve(
          Response.json({ tts: languages.length > 0, tts_languages: languages }),
        );
      }
      const body = JSON.parse(String(init.body));
      requests.push(body);
      return new Promise<Response>((resolve, reject) => {
        init.signal?.addEventListener("abort", () =>
          reject(new DOMException("aborted", "AbortError")),
        );
        void Promise.resolve(respond(body)).then(resolve);
      });
    }),
  );
}

async function load(languages = ["en-US", "en-GB"]) {
  vi.resetModules();
  stubFetch(languages);
  const speech = await import("@/lib/speech");
  await speech.loadCapabilities();
  return speech;
}

const flush = () => vi.advanceTimersByTimeAsync(0);
/** The server sentence playing now ends. */
async function endAudio() {
  players.at(-1)!.onended!();
  await flush();
}
const playing = () => players.at(-1)?.src;
const read = () => spoken.map((u) => u.text);

beforeEach(() => {
  vi.useFakeTimers();
  spoken = [];
  players = [];
  requests = [];
  respond = () => audio();
  window.localStorage.clear();
  vi.stubGlobal("speechSynthesis", {
    getVoices: () => [ZIRA, HUIHUI],
    cancel: vi.fn(() => {
      spoken = [];
    }),
    speak: (u: Utterance) => spoken.push(u),
  });
  vi.stubGlobal(
    "SpeechSynthesisUtterance",
    class {
      lang = "";
      voice = null;
      rate = 1;
      onstart = null;
      onend = null;
      onerror = null;
      constructor(public text: string) {}
    },
  );
  vi.stubGlobal(
    "Audio",
    class implements Player {
      src = "";
      paused = true;
      playbackRate = 1;
      defaultPlaybackRate = 1;
      onended = null;
      onerror = null;
      constructor() {
        players.push(this);
      }
      play() {
        this.paused = false;
        return Promise.resolve();
      }
      pause() {
        this.paused = true;
      }
    },
  );
  let n = 0;
  URL.createObjectURL = () => `blob:${++n}`;
  URL.revokeObjectURL = vi.fn();
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("server read-aloud", () => {
  it("reads English sentence by sentence on the server, fetching the next while one plays", async () => {
    const speech = await load();
    speech.speakSegments("m1", [{ text: "Good job! Say it again.", lang: "en-US" }]);
    await flush();
    expect(requests).toEqual([
      { text: "Good job!", language: "en-US", speed: 0.9 },
      { text: "Say it again.", language: "en-US", speed: 0.9 },
    ]);
    expect(playing()).toBe("blob:1");
    expect(read()).toEqual([]);

    await endAudio();
    expect(playing()).toBe("blob:2");
    await endAudio();
    expect(requests).toHaveLength(2);
    expect(URL.revokeObjectURL).toHaveBeenCalledTimes(2);
  });

  it("asks in the learner's accent and speed, and leaves Chinese to the browser", async () => {
    window.localStorage.setItem("lingo.speech", JSON.stringify({ accent: "en-GB", enRate: 1.1 }));
    const speech = await load();
    const skipped = speech.speakSegments("m1", [
      { text: "Well done.", lang: "en-US" },
      { text: "你说得对。", lang: "zh-CN" },
    ]);
    expect(skipped).toEqual([]);
    await flush();
    expect(requests).toEqual([{ text: "Well done.", language: "en-GB", speed: 1.1 }]);
    await endAudio();
    expect(read()).toEqual(["你说得对。"]);
  });

  it("asks for a word at speed 1 and plays it at the learner's speed (Q55a)", async () => {
    window.localStorage.setItem("lingo.speech", JSON.stringify({ accent: "en-GB", enRate: 0.8 }));
    const speech = await load();
    speech.speakWord(" abandon ");
    await flush();
    // Speed 1 is what the deployment generated ahead of time: the cache has it.
    expect(requests).toEqual([{ text: "abandon", language: "en-GB", speed: 1 }]);
    expect(players.at(-1)!.playbackRate).toBe(0.8);

    // A sentence is still asked at the learner's speed and played as it comes.
    requests = [];
    speech.speak("Abandon ship.");
    await flush();
    expect(requests).toEqual([{ text: "Abandon ship.", language: "en-GB", speed: 0.8 }]);
    expect(players.at(-1)!.playbackRate).toBe(1);
  });

  it("falls back to the browser for the page when the server fails", async () => {
    const speech = await load();
    respond = () => failure(502, "tts_unavailable");
    speech.speakSegments("m1", [{ text: "One. Two.", lang: "en-US" }]);
    await flush();
    expect(read()).toEqual(["One.", "Two."]);

    requests = [];
    speech.speak("Three.");
    expect(read()).toEqual(["Three."]);
    expect(requests).toEqual([]);
  });

  it("falls back when the server hasn't answered in 4 seconds", async () => {
    const speech = await load();
    respond = () => new Promise<Response>(() => {});
    speech.speak("Slow server.");
    await vi.advanceTimersByTimeAsync(speech.SERVER_START_TIMEOUT_MS - 1);
    expect(read()).toEqual([]);
    await vi.advanceTimersByTimeAsync(1);
    expect(read()).toEqual(["Slow server."]);
  });

  it("gives the browser only the language the route has no voice for", async () => {
    const speech = await load(["en-US", "zh-CN"]);
    respond = (body) => (body.language === "zh-CN" ? failure(409, "no_tts_voice") : audio());
    const segments = [
      { text: "你说得对。", lang: "zh-CN" as const },
      { text: "Again.", lang: "en-US" as const },
    ];
    speech.speakSegments("m1", segments);
    await flush();
    expect(read()).toEqual(["你说得对。"]);
    spoken[0].onend!();
    await flush();
    expect(playing()).toBe("blob:1");

    requests = [];
    speech.speakSegments("m2", segments);
    await flush();
    expect(requests.map((r) => r.language)).toEqual([]); // Chinese first, in the browser
    expect(read()).toEqual(["你说得对。"]);
  });

  it("stops the request and the audio on stop", async () => {
    const speech = await load();
    speech.speakSegments("m1", [{ text: "One. Two.", lang: "en-US" }]);
    await flush();
    const player = players.at(-1)!;
    expect(player.paused).toBe(false);
    speech.stopSpeaking();
    expect(player.paused).toBe(true);
    await flush();
    expect(read()).toEqual([]);
    expect(players.at(-1)!.src).toBe("blob:1");
  });

  it("reads with this device's voices only when the learner turned the server off", async () => {
    window.localStorage.setItem("lingo.speech", JSON.stringify({ server: false }));
    const speech = await load();
    speech.speak("Local, please.");
    await flush();
    expect(requests).toEqual([]);
    expect(read()).toEqual(["Local, please."]);
  });

  it("reads in the browser until the backend has said what it reads", async () => {
    vi.resetModules();
    stubFetch(["en-US"]);
    const speech = await import("@/lib/speech");
    speech.speak("Too soon.");
    expect(read()).toEqual(["Too soon."]);
    await flush();
    expect(requests).toEqual([]);
  });
});

describe("reading a reply while it streams (task 59.1)", () => {
  it("asks for each sentence once it is complete, and the rest at the end", async () => {
    const speech = await load();
    const stream = speech.speakStream("m1");
    stream.push("Nice to meet");
    stream.push(" you. What's your **name**? I'm");
    await flush();
    // The second is fetched while the first plays.
    expect(requests.map((r) => r.text)).toEqual(["Nice to meet you.", "What's your name?"]);
    await endAudio();
    await endAudio();
    stream.push(" Sam, 3.5 years");
    stream.end();
    await flush();
    expect(requests.at(-1)!.text).toBe("I'm Sam, 3.5 years");
    expect(playing()).toBe("blob:3");
  });

  it("waits for the next sentence in the browser too, and ends after the last", async () => {
    const speech = await load([]);
    const stream = speech.speakStream("m1");
    stream.push("Hello there. And");
    expect(read()).toEqual(["Hello there."]);
    spoken[0].onend!();
    stream.push(" goodbye.");
    stream.end();
    expect(read()).toEqual(["And goodbye."]);
  });

  it("ignores what comes after it was stopped", async () => {
    const speech = await load();
    const stream = speech.speakStream("m1");
    stream.push("One. ");
    await flush();
    speech.stopSpeaking();
    stream.push("Two. ");
    stream.end();
    await flush();
    expect(requests.map((r) => r.text)).toEqual(["One."]);
  });
});
