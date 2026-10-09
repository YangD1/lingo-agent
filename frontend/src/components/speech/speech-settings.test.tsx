import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { parseSpeechSettings, speak } from "@/lib/speech";
import type { VoiceLike } from "@/lib/voices";

import en from "../../../messages/en.json";
import { SpeechSettings } from "./speech-settings";

const v = (name: string, lang: string, local = false): VoiceLike => ({
  name,
  lang,
  localService: local,
  default: false,
  voiceURI: name,
});

const AVA = v("Microsoft AvaMultilingual Online (Natural) - English (United States)", "en-US");
const ZIRA = v("Microsoft Zira - English (United States)", "en-US", true);
const SONIA = v("Microsoft Sonia Online (Natural) - English (United Kingdom)", "en-GB");
const XIAOXIAO = v("Microsoft Xiaoxiao Online (Natural) - Chinese (Mainland)", "zh-CN");

type Spoken = { text: string; lang: string; voice: VoiceLike | null; rate: number };

// One browser for the whole file: the speech module listens for `voiceschanged` once.
const synth = {
  voices: [] as VoiceLike[],
  spoken: [] as Spoken[],
  onVoicesChanged: [] as (() => void)[],
  getVoices() {
    return this.voices;
  },
  addEventListener(type: string, listener: () => void) {
    if (type === "voiceschanged") this.onVoicesChanged.push(listener);
  },
  speak(utterance: Spoken) {
    this.spoken.push(utterance);
  },
  cancel() {},
};

function listVoices(voices: VoiceLike[]) {
  synth.voices = voices;
  act(() => synth.onVoicesChanged.forEach((listener) => listener()));
}

function wrap() {
  return render(
    <NextIntlClientProvider locale="en" messages={en} timeZone="UTC">
      <SpeechSettings />
    </NextIntlClientProvider>,
  );
}

beforeEach(() => {
  synth.voices = [AVA, ZIRA, SONIA, XIAOXIAO];
  synth.spoken = [];
  vi.stubGlobal("speechSynthesis", synth);
  vi.stubGlobal(
    "SpeechSynthesisUtterance",
    class {
      lang = "";
      voice: VoiceLike | null = null;
      rate = 1;
      onend: (() => void) | null = null;
      onerror: (() => void) | null = null;
      constructor(public text: string) {}
    },
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
  window.localStorage.clear();
  window.dispatchEvent(new Event("lingo:speech"));
});

describe("parseSpeechSettings", () => {
  it("falls back to the defaults for anything missing, broken or out of range", () => {
    const defaults = { accent: "en-US", enRate: 0.9, enVoice: null, server: true, zhVoice: null };
    expect(parseSpeechSettings(null)).toEqual(defaults);
    expect(parseSpeechSettings("not json")).toEqual(defaults);
    expect(parseSpeechSettings('{"accent":"fr-FR","enRate":"fast","enVoice":3}')).toEqual(defaults);
    expect(parseSpeechSettings('{"accent":"en-GB","enRate":3,"zhVoice":"x"}')).toEqual({
      ...defaults,
      accent: "en-GB",
      enRate: 1.2,
      zhVoice: "x",
    });
  });
});

describe("SpeechSettings", () => {
  it("shows what “automatic” picks, and follows the accent", async () => {
    wrap();
    const english = screen.getByLabelText("English voice");
    expect(english).toHaveDisplayValue(`Automatic (now: ${AVA.name})`);
    expect(screen.getByLabelText("Chinese voice")).toHaveDisplayValue(`Automatic (now: ${AVA.name})`);

    await userEvent.click(screen.getByLabelText("British"));
    expect(english).toHaveDisplayValue(`Automatic (now: ${SONIA.name})`);
    expect(screen.getByLabelText("Chinese voice")).toHaveDisplayValue(
      `Automatic (now: ${XIAOXIAO.name})`,
    );
    expect(JSON.parse(window.localStorage.getItem("lingo.speech")!)).toMatchObject({
      accent: "en-GB",
    });
  });

  it("saves a chosen voice and speed, which every read-aloud then uses", async () => {
    wrap();
    await userEvent.selectOptions(screen.getByLabelText("English voice"), ZIRA.name);
    fireEvent.change(screen.getByLabelText(/English speed/), { target: { value: "1.2" } });
    expect(screen.getByText("1.2×")).toBeInTheDocument();

    await userEvent.click(screen.getAllByRole("button", { name: "Try" })[0]);
    expect(synth.spoken.at(-1)).toMatchObject({ voice: ZIRA, rate: 1.2 });
    // The word popup and the review page read with the same settings.
    speak("abandon");
    expect(synth.spoken.at(-1)).toMatchObject({ text: "abandon", voice: ZIRA, rate: 1.2 });
    expect(JSON.parse(window.localStorage.getItem("lingo.speech")!)).toMatchObject({
      enVoice: ZIRA.name,
      enRate: 1.2,
    });
  });

  it("says when the device has no Chinese voice", () => {
    synth.voices = [ZIRA];
    wrap();
    expect(screen.getByText(/no Chinese voice/)).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Try" })[1]).toBeDisabled();
  });

  it("waits for the browser to list its voices", () => {
    synth.voices = [];
    wrap();
    expect(screen.getByLabelText("English voice")).toBeDisabled();
    expect(screen.getByText(/hasn't listed its voices/)).toBeInTheDocument();

    listVoices([ZIRA, XIAOXIAO]);
    expect(screen.getByLabelText("English voice")).toBeEnabled();
    expect(screen.getByLabelText("English voice")).toHaveDisplayValue(
      `Automatic (now: ${ZIRA.name})`,
    );
  });
});
