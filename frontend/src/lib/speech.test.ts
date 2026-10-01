import { describe, expect, it } from "vitest";

import { DEFAULT_SPEECH_SETTINGS, planSpeech, revoice, splitSentences } from "@/lib/speech";
import type { VoiceLike } from "@/lib/voices";

const v = (name: string, lang: string): VoiceLike => ({
  name,
  lang,
  localService: false,
  default: false,
  voiceURI: name,
});

const ARIA = v("Microsoft Aria Online (Natural) - English (United States)", "en-US");
const XIAOXIAO = v("Microsoft Xiaoxiao Online (Natural) - Chinese (Mainland)", "zh-CN");
const AVA = v("Microsoft AvaMultilingual Online (Natural) - English (United States)", "en-US");
const ZIRA = { ...v("Microsoft Zira - English (United States)", "en-US"), localService: true };
const HUIHUI = { ...v("Microsoft Huihui - Chinese (Simplified, PRC)", "zh-CN"), localService: true };
const SONIA = v("Microsoft Sonia Online (Natural) - English (United Kingdom)", "en-GB");

describe("splitSentences", () => {
  it("cuts after sentence ends and line breaks, keeping decimals whole", () => {
    expect(splitSentences("I went home. It was 3.5 km away! Really?\nYes")).toEqual([
      "I went home.",
      "It was 3.5 km away!",
      "Really?",
      "Yes",
    ]);
    expect(splitSentences("你说得对。再说一遍！好吗？")).toEqual(["你说得对。", "再说一遍！", "好吗？"]);
  });

  it("cuts a very long sentence after its commas, and drops bare punctuation", () => {
    const clause = "and then we walked along the river for a very long time";
    const long = Array(5).fill(clause).join(", ") + ".";
    const pieces = splitSentences(long);
    expect(pieces).toHaveLength(5);
    expect(pieces.every((piece) => piece.length <= 200)).toBe(true);
    expect(pieces.join(" ")).toBe(long);
    expect(splitSentences(" “ ")).toEqual([]);
  });
});

describe("planSpeech", () => {
  const segments = [
    { text: "Good job! Say it again.", lang: "en-US" as const },
    { text: "你说得对。", lang: "zh-CN" as const },
  ];

  it("reads each language with its voice, English at the learner's speed", () => {
    const { utterances, skipped } = planSpeech(segments, [ARIA, XIAOXIAO], DEFAULT_SPEECH_SETTINGS);
    expect(skipped).toEqual([]);
    expect(utterances.map(({ text, lang, voice, rate }) => [text, lang, voice?.name, rate])).toEqual([
      ["Good job!", "en-US", ARIA.name, 0.9],
      ["Say it again.", "en-US", ARIA.name, 0.9],
      ["你说得对。", "zh-CN", XIAOXIAO.name, 1],
    ]);
  });

  it("a multilingual voice reads the Chinese too, told it's Chinese", () => {
    const { utterances } = planSpeech(segments, [AVA, XIAOXIAO], DEFAULT_SPEECH_SETTINGS);
    expect(utterances.map(({ voice, lang }) => [voice?.name, lang])).toEqual([
      [AVA.name, "en-US"],
      [AVA.name, "en-US"],
      [AVA.name, "zh-CN"],
    ]);
  });

  it("leaves Chinese out when the device has no Chinese voice", () => {
    const { utterances, skipped } = planSpeech(segments, [ARIA], DEFAULT_SPEECH_SETTINGS);
    expect(utterances.map((u) => u.text)).toEqual(["Good job!", "Say it again."]);
    expect(skipped).toEqual(["zh-CN"]);
  });

  it("goes by language alone before the browser lists its voices", () => {
    const settings = { ...DEFAULT_SPEECH_SETTINGS, accent: "en-GB" as const, enRate: 1.2 };
    const { utterances } = planSpeech(segments, [], settings);
    expect(utterances.map(({ lang, voice, rate }) => [lang, voice, rate])).toEqual([
      ["en-GB", null, 1.2],
      ["en-GB", null, 1.2],
      ["zh-CN", null, 1],
    ]);
  });

  it("follows the accent", () => {
    const settings = { ...DEFAULT_SPEECH_SETTINGS, accent: "en-GB" as const };
    const { utterances } = planSpeech(segments.slice(0, 1), [ARIA, SONIA], settings);
    expect(utterances[0].voice?.name).toBe(SONIA.name);
    expect(utterances[0].lang).toBe("en-GB");
  });
});

describe("revoice", () => {
  it("swaps a failed voice for the best one left, piece by piece", () => {
    const segments = [
      { text: "Good job! Say it again.", lang: "en-US" as const },
      { text: "你说得对。", lang: "zh-CN" as const },
    ];
    const voices = [AVA, ZIRA, XIAOXIAO, HUIHUI];
    const { utterances } = planSpeech(segments, voices, DEFAULT_SPEECH_SETTINGS);
    // The multilingual voice reads everything; when it fails, each language gets its own.
    const failed = new Set([AVA.voiceURI]);
    const again = revoice(utterances.slice(1), voices, { ...DEFAULT_SPEECH_SETTINGS, failed });
    expect(again.utterances.map(({ text, voice, lang }) => [text, voice?.name, lang])).toEqual([
      ["Say it again.", ZIRA.name, "en-US"],
      ["你说得对。", XIAOXIAO.name, "zh-CN"],
    ]);
  });

  it("keeps pieces whose voice works, and drops a language with no voice left", () => {
    const voices = [ZIRA, XIAOXIAO];
    const { utterances } = planSpeech(
      [
        { text: "Hi.", lang: "en-US" },
        { text: "你好。", lang: "zh-CN" },
      ],
      voices,
      DEFAULT_SPEECH_SETTINGS,
    );
    const failed = new Set([XIAOXIAO.voiceURI]);
    const again = revoice(utterances, voices, { ...DEFAULT_SPEECH_SETTINGS, failed });
    expect(again.utterances.map((u) => [u.text, u.voice?.name])).toEqual([["Hi.", ZIRA.name]]);
    expect(again.skipped).toEqual(["zh-CN"]);
  });
});
