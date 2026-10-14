import { describe, expect, it } from "vitest";

import {
  DEFAULT_TUTOR,
  type Tutor,
  type TutorOptions,
  formChanged,
  splitRef,
  toBody,
  toForm,
  voicesFor,
} from "./tutor";
import type { VoiceOption } from "./types";

const voice = (id: string, languages: VoiceOption["languages"], accent: string | null = null) =>
  ({ id, name: id, gender: null, languages, accent, note: "" }) as VoiceOption;

const OPTIONS: TutorOptions = {
  chat: { models: ["openai:gpt-5-mini", "qwen:qwen-plus"], provided_by: null, quota_exhausted: false },
  read_aloud: {
    models: ["qwen:qwen3-tts-flash"],
    provided_by: null,
    quota_exhausted: false,
    voice_model: "qwen:qwen3-tts-flash",
    voice_options: [],
    default_voices: { "en-US": "Cherry", "en-GB": "Cherry", "zh-CN": "Cherry" },
  },
  realtime: {
    models: ["openai:gpt-realtime"],
    provided_by: null,
    quota_exhausted: false,
    voice_options: {},
    default_voices: {},
  },
};

const SAVED: Tutor = {
  ...DEFAULT_TUTOR,
  name: "Max",
  avatar: "sporty",
  chat_model: "qwen:qwen-plus",
  tts_model: "qwen:qwen3-tts-flash",
  voices: { "en-US": "Ethan" },
  realtime_model: "openai:gpt-realtime",
  realtime_voice: "cedar",
};

describe("tutor form", () => {
  it("round-trips what is saved", () => {
    const form = toForm(SAVED, OPTIONS);
    expect(form.voices).toEqual({ "en-US": "Ethan", "en-GB": "", "zh-CN": "" });
    expect(toBody(form, OPTIONS)).toEqual({
      name: "Max",
      avatar: "sporty",
      color: null,
      animate: true,
      pet: true,
      nudges: true,
      daily_opening: true,
      chat_model: "qwen:qwen-plus",
      tts_model: "qwen:qwen3-tts-flash",
      voices: { "en-US": "Ethan" },
      realtime_model: "openai:gpt-realtime",
      realtime_voice: "cedar",
    });
    expect(formChanged(SAVED, form, OPTIONS)).toBe(false);
    expect(formChanged(SAVED, { ...form, pet: false }, OPTIONS)).toBe(true);
    expect(formChanged(SAVED, { ...form, daily_opening: false }, OPTIONS)).toBe(true);
    expect(formChanged(SAVED, { ...form, nudges: false }, OPTIONS)).toBe(true);
    // Only spaces in the name: the default name.
    expect(formChanged(SAVED, { ...form, name: " Max  " }, OPTIONS)).toBe(false);
  });

  it("drops choices that can't be used now, as saving them would be refused", () => {
    const form = toForm({ ...SAVED, unavailable: ["chat_model", "realtime_model"] }, OPTIONS);
    expect([form.chat_model, form.realtime_model, form.realtime_voice]).toEqual(["", "", ""]);
    // Voices for another read-aloud model than the one in use.
    const moved = { ...OPTIONS, read_aloud: { ...OPTIONS.read_aloud, voice_model: "x:y" } };
    expect(toForm(SAVED, moved).voices["en-US"]).toBe("");
  });

  it("sends the read-aloud model only with voices, and a call voice only with its model", () => {
    const form = { ...toForm(DEFAULT_TUTOR, OPTIONS), realtime_voice: "cedar" };
    const body = toBody(form, OPTIONS);
    expect([body.tts_model, body.realtime_model, body.realtime_voice]).toEqual([null, null, null]);
    expect(body.avatar).toBe("cat");
  });
});

describe("splitRef", () => {
  it("splits at the first colon only", () => {
    expect(splitRef("ollama:qwen3:8b")).toEqual({ connection: "ollama", model: "qwen3:8b" });
    expect(splitRef("bare")).toEqual({ connection: "", model: "bare" });
  });
});

describe("voicesFor", () => {
  it("lists a language's voices, those of that accent first", () => {
    const options = [
      voice("a", ["en-US", "en-GB"], "en-US"),
      voice("b", ["en-US", "en-GB"], "en-GB"),
      voice("c", ["zh-CN"]),
    ];
    expect(voicesFor(options, "en-GB").map((o) => o.id)).toEqual(["b", "a"]);
    expect(voicesFor(options, "zh-CN").map((o) => o.id)).toEqual(["c"]);
  });
});
