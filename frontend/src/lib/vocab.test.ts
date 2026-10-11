import { describe, expect, it } from "vitest";

import {
  type Card,
  cardFormat,
  formatInterval,
  judgeSpelling,
  listenOptions,
  spellingMarks,
} from "./vocab";

describe("formatInterval", () => {
  it("rounds to the unit a learner thinks in", () => {
    expect(formatInterval(0, "en")).toBe("<1 min");
    expect(formatInterval(330, "en")).toBe("6 min");
    expect(formatInterval(3 * 3600 + 100, "en")).toBe("3 hr");
    expect(formatInterval(4 * 86_400, "en")).toBe("4 days");
    expect(formatInterval(65 * 86_400, "en")).toBe("2 mths");
    expect(formatInterval(550 * 86_400, "en")).toBe("1.5 yrs");
  });

  it("speaks the interface language", () => {
    expect(formatInterval(600, "zh-CN")).toBe("10分钟");
    expect(formatInterval(86_400, "zh-CN")).toBe("1天");
  });
});

const card = (overrides: Partial<Card> = {}): Card => ({
  word: { id: 1, word: "apple", phonetic: null, translation: "n. 苹果", definition: null },
  source: "book",
  status: "learning",
  due: null,
  last_review: "2026-10-01T00:00:00Z",
  intervals: [60, 600, 86_400, 864_000],
  sentences: [],
  forms: ["apple"],
  ai_examples: [],
  gloss: "n. 苹果",
  choices: ["n. 香蕉", "n. 面包", "n. 奶酪"],
  ...overrides,
});

describe("cardFormat", () => {
  it("shows the format picked, for words reviewed before", () => {
    expect(cardFormat(card(), "listen", true, 0)).toBe("listen");
    expect(cardFormat(card(), "spell", true, 0)).toBe("spell");
    expect(cardFormat(card(), "recognize", true, 0)).toBe("recognize");
  });

  it("recognises new words, and everything when nothing reads aloud", () => {
    expect(cardFormat(card({ last_review: null }), "spell", true, 0)).toBe("recognize");
    expect(cardFormat(card(), "listen", false, 0)).toBe("recognize");
    expect(cardFormat(card(), "mixed", false, 1)).toBe("recognize");
  });

  it("listens only with three wrong meanings; mixed draws by the seed", () => {
    expect(cardFormat(card({ choices: ["n. 香蕉"] }), "listen", true, 0)).toBe("recognize");
    expect([0, 1, 2].map((seed) => cardFormat(card(), "mixed", true, seed))).toEqual([
      "recognize",
      "listen",
      "spell",
    ]);
    const short = card({ choices: [] });
    expect([0, 1, 2].map((seed) => cardFormat(short, "mixed", true, seed))).toEqual([
      "recognize",
      "spell",
      "recognize",
    ]);
  });
});

describe("listenOptions", () => {
  it("holds the right meaning and the wrong ones, the same order for the same seed", () => {
    const options = listenOptions(card(), 42);
    expect([...options].sort()).toEqual(["n. 奶酪", "n. 苹果", "n. 面包", "n. 香蕉"].sort());
    expect(listenOptions(card(), 42)).toEqual(options);
    const places = new Set(
      Array.from({ length: 40 }, (_, seed) => listenOptions(card(), seed).indexOf("n. 苹果")),
    );
    expect(places.size).toBe(4);
  });
});

describe("judgeSpelling", () => {
  it("ignores case and spaces, allows nothing else", () => {
    expect(judgeSpelling("  Apple ", "apple")).toBe("right");
    expect(judgeSpelling("give  up", "give up")).toBe("right");
    expect(judgeSpelling("us", "US")).toBe("right");
    expect(judgeSpelling("aple", "apple")).toBe("close");
    expect(judgeSpelling("applle", "apple")).toBe("close");
    expect(judgeSpelling("apply", "apple")).toBe("close");
    expect(judgeSpelling("apples", "apple")).toBe("close");
    expect(judgeSpelling("went", "go")).toBe("wrong");
    expect(judgeSpelling("", "apple")).toBe("wrong");
  });
});

describe("spellingMarks", () => {
  const missed = (typed: string, word: string) =>
    spellingMarks(typed, word)
      .map((m) => (m.ok ? m.char : `[${m.char}]`))
      .join("");

  it("marks the letters of the word the learner missed", () => {
    expect(missed("apple", "apple")).toBe("apple");
    // A doubled letter: either one is the missed one.
    expect(missed("aple", "apple")).toBe("a[p]ple");
    expect(missed("recieve", "receive")).toBe("rec[e][i]ve");
    expect(missed("", "go")).toBe("[g][o]");
    expect(missed("APPLES", "Apple")).toBe("Apple");
  });
});
