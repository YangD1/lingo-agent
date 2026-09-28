import { describe, expect, it } from "vitest";

import { chatModelIds, modelsOfRefs, recommendModel } from "./models";

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
