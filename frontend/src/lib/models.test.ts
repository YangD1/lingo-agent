import { describe, expect, it } from "vitest";

import { chatModelIds, modelsOfRefs, recommendModel, speechModelIds } from "./models";

describe("chatModelIds", () => {
  it("keeps only chat models, in order", () => {
    expect(
      chatModelIds([
        { id: "gpt-4o", category: "chat" },
        { id: "text-embedding-3-small", category: "embedding" },
        { id: "whisper-1", category: "other" },
        { id: "gpt-4o-mini", category: "chat" },
      ]),
    ).toEqual(["gpt-4o", "gpt-4o-mini"]);
  });
});

describe("modelsOfRefs", () => {
  it("strips the connection and skips malformed refs", () => {
    expect(modelsOfRefs(["deepseek:deepseek-chat", "dd:org/model:free", "bare", ":x"])).toEqual([
      "deepseek-chat",
      "org/model:free",
    ]);
  });
});

describe("recommendModel", () => {
  const available = ["a-model", "deepseek-chat", "gpt-4o-mini"];

  it("prefers the first preferred model the connection serves", () => {
    expect(recommendModel(available, ["claude-x", "gpt-4o-mini", "deepseek-chat"])).toBe(
      "gpt-4o-mini",
    );
  });

  it("falls back to the first available model", () => {
    expect(recommendModel(available, ["claude-x"])).toBe("a-model");
  });

  it("is empty when nothing is available", () => {
    expect(recommendModel([], ["deepseek-chat"])).toBe("");
  });
});

describe("speechModelIds", () => {
  it("keeps transcription models only", () => {
    expect(
      speechModelIds([
        { id: "whisper-large-v3-turbo", category: "other" },
        { id: "gpt-transcribe", category: "other" },
        { id: "tts-1", category: "other" },
        { id: "gpt-5-mini", category: "chat" },
        { id: "FunAudioLLM/SenseVoiceSmall", category: "other" },
      ]),
    ).toEqual(["whisper-large-v3-turbo", "gpt-transcribe", "FunAudioLLM/SenseVoiceSmall"]);
  });
});
