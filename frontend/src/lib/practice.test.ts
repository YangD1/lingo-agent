import { describe, expect, it } from "vitest";

import { type Item, keyText, practiceSetHref, replyText } from "@/lib/practice";

const KC = { id: "g.third", name_en: "Third", name_zh: "三单", cefr: "A1" as const };
const item = (overrides: Partial<Item>): Item => ({
  id: 1,
  position: 0,
  kc: KC,
  format: "choice4",
  content: {},
  status: "ok",
  from_bank: false,
  answer: null,
  result: null,
  ...overrides,
});

describe("practice helpers", () => {
  it("links entry points to a set, with the grammar point when there is one", () => {
    expect(practiceSetHref("learner", "g.third")).toBe("/practice?from=learner&kc=g.third");
    expect(practiceSetHref("dashboard")).toBe("/practice?from=dashboard");
  });

  it("writes the key out as a sentence", () => {
    const explanation = "x";
    expect(keyText(item({ answer: { correct: "lives", explanation } }))).toBe("lives");
    expect(
      keyText(
        item({
          format: "cloze",
          content: { stem: "He ___ here." },
          answer: { accepted: ["lives"], explanation },
        }),
      ),
    ).toBe("He lives here.");
    expect(
      keyText(
        item({
          format: "find_fix",
          content: { segments: ["He ", "go ", "to work."] },
          answer: { wrong_segment: 1, accepted: ["goes "], explanation },
        }),
      ),
    ).toBe("He goes to work.");
    expect(keyText(item({ format: "translate" }))).toBe("");
  });

  it("writes the learner's answer out as a sentence", () => {
    const fix = item({ format: "find_fix", content: { segments: ["He ", "go ", "to work."] } });
    expect(replyText(fix, { segment: 1, fix: "goes " })).toBe("He goes to work.");
    expect(replyText(item({}), { choice: "live" })).toBe("live");
    expect(replyText(item({ format: "translate" }), { text: "She walks." })).toBe("She walks.");
  });
});
