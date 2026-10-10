import { describe, expect, it } from "vitest";

import { gradeWord, shadowingSentences } from "./shadowing";

describe("shadowingSentences", () => {
  it("cuts English at sentence ends", () => {
    expect(shadowingSentences("I like tea. Do you? Let's go!")).toEqual([
      "I like tea.",
      "Do you?",
      "Let's go!",
    ]);
  });

  it("keeps the English of a reply mixed with Chinese", () => {
    expect(
      shadowingSentences("这句可以说成：I have been working here for three years. 注意时态。"),
    ).toEqual(["I have been working here for three years."]);
  });

  it("drops lone words and list markers", () => {
    expect(shadowingSentences("OK\n- She goes to school.\n2. He is tall.\nB1")).toEqual([
      "She goes to school.",
      "He is tall.",
    ]);
  });

  it("drops sentences too long for one reading, and repeats", () => {
    const long = `${"word ".repeat(130)}end.`;
    expect(shadowingSentences(`${long} Say it again. Say it again.`)).toEqual(["Say it again."]);
  });
});

describe("gradeWord", () => {
  it("grades assessed words by accuracy", () => {
    expect(gradeWord({ word: "a", accuracy: 92, error: "None" })).toBe("good");
    expect(gradeWord({ word: "a", accuracy: 70, error: "None" })).toBe("fair");
    expect(gradeWord({ word: "a", accuracy: 40, error: "Mispronunciation" })).toBe("poor");
    expect(gradeWord({ word: "a", accuracy: 85, error: "Mispronunciation" })).toBe("fair");
    expect(gradeWord({ word: "a", accuracy: null, error: "Omission" })).toBe("missed");
    expect(gradeWord({ word: "a", accuracy: 90, error: "Insertion" })).toBe("extra");
  });

  it("grades rough words by what was heard", () => {
    expect(gradeWord({ word: "a", error: "none" })).toBe("good");
    expect(gradeWord({ word: "a", error: "omission" })).toBe("missed");
    expect(gradeWord({ word: "a", error: "substitution", heard: "the" })).toBe("poor");
    expect(gradeWord({ word: "a", error: "insertion" })).toBe("extra");
  });
});
