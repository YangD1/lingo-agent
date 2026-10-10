import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import en from "../../../messages/en.json";
import { ApiError } from "@/lib/api";
import type { ShadowingMode, ShadowingResult } from "@/lib/shadowing";

// The recorder, the scoring request and read-aloud are stand-ins: the panel is what's tested.
const rec = vi.hoisted(() => ({
  recording: false,
  seconds: 0,
  level: 0,
  error: null as string | null,
  start: vi.fn(),
  stop: vi.fn(),
  cancel: vi.fn(),
  onRecorded: null as ((file: File) => void) | null,
}));
vi.mock("./use-wav-recorder", () => ({
  MAX_SHADOWING_SECONDS: 30,
  useWavRecorder: (onRecorded: (file: File) => void) => {
    rec.onRecorded = onRecorded;
    return rec;
  },
}));

const mocks = vi.hoisted(() => ({
  mode: "assessment" as ShadowingMode | null,
  submit: vi.fn(),
  speakSegments: vi.fn(),
  stopSpeaking: vi.fn(),
  addMine: vi.fn(),
}));
vi.mock("@/lib/shadowing", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/shadowing")>()),
  useShadowingMode: () => mocks.mode,
  submitShadowing: mocks.submit,
}));
vi.mock("@/lib/speech", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/speech")>()),
  useCanSpeak: () => true,
  useSpeaking: () => false,
  useSpeechSettings: () => [{ accent: "en-GB" }, () => {}],
  speakSegments: mocks.speakSegments,
  stopSpeaking: mocks.stopSpeaking,
}));
vi.mock("@/lib/vocab", () => ({ addMine: mocks.addMine }));

const { ShadowingPanel } = await import("./shadowing-panel");

const ASSESSED: ShadowingResult = {
  id: "a1",
  source: "chat",
  source_id: "m1",
  reference_text: "I think so.",
  language: "en-GB",
  mode: "assessment",
  fallback_reason: null,
  scores: { overall: 82, accuracy: 85, fluency: 90, completeness: 100, prosody: null },
  words: [
    { word: "I", accuracy: 95, error: "None", phonemes: [] },
    {
      word: "think",
      accuracy: 42,
      error: "Mispronunciation",
      phonemes: [
        { phoneme: null, accuracy: 20 },
        { phoneme: null, accuracy: 90 },
      ],
    },
    { word: "so", accuracy: null, error: "Omission", phonemes: [] },
  ],
  recognized_text: "I sink",
  audio_seconds: 1.5,
  counted: true,
  created_at: "2026-10-10T00:00:00Z",
  mispronounced: ["think"],
};

const ROUGH: ShadowingResult = {
  ...ASSESSED,
  id: "r1",
  mode: "rough",
  fallback_reason: "not_configured",
  scores: null,
  words: [
    { word: "I", error: "none" },
    { word: "think", error: "substitution", heard: "sink" },
    { word: "so", error: "omission" },
  ],
  counted: false,
  mispronounced: [],
};

function show(sentences = ["I think so.", "See you later."]) {
  return render(
    <NextIntlClientProvider locale="en" messages={en} timeZone="UTC">
      <ShadowingPanel sentences={sentences} source="chat" sourceId="m1" onClose={() => {}} />
    </NextIntlClientProvider>,
  );
}

async function readBack(result: ShadowingResult | Error) {
  if (result instanceof Error) mocks.submit.mockRejectedValueOnce(result);
  else mocks.submit.mockResolvedValueOnce(result);
  await userEvent.click(screen.getByTestId("shadowing-record"));
  await act(async () => rec.onRecorded!(new File(["x"], "s.wav", { type: "audio/wav" })));
}

beforeEach(() => {
  mocks.mode = "assessment";
  rec.recording = false;
  rec.error = null;
  vi.clearAllMocks();
});

describe("ShadowingPanel", () => {
  it("shows nothing while shadowing can't be scored", () => {
    mocks.mode = null;
    show();
    expect(screen.queryByTestId("shadowing-panel")).toBeNull();
  });

  it("lets the learner pick the sentence to read", async () => {
    show();
    expect(screen.getByTestId("shadowing-sentence")).toHaveTextContent("I think so.");
    await userEvent.click(screen.getByRole("button", { name: "See you later." }));
    expect(screen.getByTestId("shadowing-sentence")).toHaveTextContent("See you later.");
    expect(screen.getByRole("button", { name: "See you later." })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("plays the example of the chosen sentence", async () => {
    show(["Only one sentence."]);
    expect(screen.queryByTestId("shadowing-sentences")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Listen" }));
    expect(mocks.speakSegments).toHaveBeenCalledWith("shadowing", [
      { text: "Only one sentence.", lang: "en-US" },
    ]);
  });

  it("stops the example, records and shows the assessment", async () => {
    show();
    await readBack(ASSESSED);

    expect(mocks.stopSpeaking).toHaveBeenCalled();
    expect(rec.start).toHaveBeenCalled();
    expect(mocks.submit).toHaveBeenCalledWith(
      expect.any(File),
      "I think so.",
      "en-GB",
      "chat",
      "m1",
      expect.any(AbortSignal),
    );
    expect(screen.getByTestId("shadowing-overall")).toHaveTextContent("82");
    expect(screen.getByTestId("shadowing-scores")).not.toHaveTextContent("Prosody");
    const words = screen.getByTestId("shadowing-words");
    expect(words.querySelector('[data-grade="poor"]')).toHaveTextContent("think");
    expect(words.querySelector('[data-grade="missed"]')).toHaveTextContent("so");
    expect(screen.getByTestId("shadowing-record")).toHaveTextContent("Read again");
  });

  it("opens a word: its score, and that British English has no phonetic symbols", async () => {
    show();
    await readBack(ASSESSED);
    await userEvent.click(screen.getByRole("button", { name: "think" }));
    const detail = screen.getByTestId("shadowing-word-detail");
    expect(detail).toHaveTextContent("accuracy 42");
    expect(detail).toHaveTextContent("no phonetic symbols");
  });

  it("adds a mispronounced word to the word list", async () => {
    mocks.addMine.mockResolvedValueOnce({ added: true });
    show();
    await readBack(ASSESSED);
    await userEvent.click(screen.getByRole("button", { name: "Add to word list" }));
    expect(mocks.addMine).toHaveBeenCalledWith("think");
    expect(await screen.findByText("Added")).toBeInTheDocument();
  });

  it("says when a reading didn't count toward speaking", async () => {
    show();
    await readBack({ ...ASSESSED, counted: false });
    expect(screen.getByText(/too short or left out too much/)).toBeInTheDocument();
  });

  it("marks a rough result as such, with what was heard", async () => {
    mocks.mode = "rough";
    show();
    await readBack(ROUGH);
    expect(screen.getByTestId("shadowing-rough")).toHaveTextContent("Rough result");
    expect(screen.getByTestId("shadowing-rough")).toHaveTextContent("1 of 3 words heard.");
    expect(screen.queryByTestId("shadowing-scores")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "think" }));
    expect(screen.getByTestId("shadowing-word-detail")).toHaveTextContent("heard as “sink”");
  });

  it("says when assessment failed and a transcript stood in", async () => {
    show();
    await readBack({ ...ROUGH, fallback_reason: "failed" });
    expect(screen.getByTestId("shadowing-rough")).toHaveTextContent("assessment failed");
  });

  it("explains a scoring error in its own words", async () => {
    show();
    await readBack(new ApiError(422, "no_speech", "no speech"));
    expect(screen.getByRole("alert")).toHaveTextContent("Couldn't make out what you read");
  });

  it("explains a browser that can't record", () => {
    rec.error = "recording_unsupported";
    show();
    expect(screen.getByRole("alert")).toHaveTextContent("can't record for shadowing");
  });

  it("moves on to the next sentence after a reading", async () => {
    show();
    await readBack(ASSESSED);
    await userEvent.click(screen.getByRole("button", { name: "Next sentence" }));
    await waitFor(() =>
      expect(screen.getByTestId("shadowing-sentence")).toHaveTextContent("See you later."),
    );
  });
});
