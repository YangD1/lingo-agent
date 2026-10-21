import { render, screen, within } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it, vi } from "vitest";

import type { Card, WordSense } from "@/lib/vocab";

import en from "../../../messages/en.json";
import zh from "../../../messages/zh-CN.json";
import { WordMeanings } from "./word-meanings";

vi.mock("@/lib/shadowing", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/shadowing")>()),
  useShadowingMode: () => null,
}));

const URL = "https://simple.wiktionary.org/wiki/run";
const sense = (pos: string, gloss: string, more: Partial<WordSense> = {}): WordSense => ({
  pos,
  gloss,
  labels: [],
  examples: [],
  synonyms: [],
  source: "simplewiktionary",
  url: URL,
  ...more,
});

const card = (senses: WordSense[]): Card => ({
  word: {
    id: 1,
    word: "run",
    phonetic: null,
    translation: "v. 跑\n[体] 得分",
    definition: "n. a score in baseball",
  },
  source: "book",
  status: "learning",
  due: null,
  last_review: null,
  intervals: [60, 330, 600, 86_400],
  sentences: [],
  senses,
  forms: ["ran", "run", "running", "runs"],
  ai_examples: [],
  gloss: "v. 跑",
  choices: [],
});

const SENSES = [
  sense("verb", "If you run, you go quickly.", { examples: ["I must run.", "I ran home."] }),
  sense("verb", "If a machine runs, it works.", {
    labels: ["intransitive", "machinery"],
    examples: ["The car runs well."],
  }),
  sense("noun", "A run is a trip made by a runner.", { examples: ["I'm going for a run."] }),
];

function show(c: Card, locale: "en" | "zh-CN" = "en") {
  return render(
    <NextIntlClientProvider locale={locale} messages={locale === "en" ? en : zh} timeZone="UTC">
      <WordMeanings card={c} />
    </NextIntlClientProvider>,
  );
}

describe("WordMeanings with dictionary senses (ADR 0062)", () => {
  it("opens the first two senses with an example each and folds the rest", () => {
    show(card(SENSES));
    const [open, folded] = screen.getAllByTestId("review-senses");
    const items = within(open).getAllByRole("listitem");
    expect(items.map((li) => li.textContent)).toEqual([
      "v.If you run, you go quickly.I must run.",
      "v.intransitivemachineryIf a machine runs, it works.The car runs well.",
    ]);
    expect([...items[0].querySelectorAll("strong")].map((b) => b.textContent)).toEqual([
      "run",
      "run",
    ]);

    const more = screen.getByTestId("review-more");
    expect(more.querySelector("summary")).toHaveTextContent(
      "More · 1 English sense · 1 specialist sense",
    );
    expect(more).toContainElement(folded);
    expect(folded).toHaveTextContent("n.A run is a trip made by a runner.I'm going for a run.");
    // ECDICT's definition gives way to the dictionary's senses.
    expect(screen.queryByText(/baseball/)).not.toBeInTheDocument();
    expect(
      within(more).getByRole("link", { name: "Source: Simple English Wiktionary (CC BY-SA)" }),
    ).toHaveAttribute("href", URL);
  });

  it("names grammar labels in Chinese and keeps the others as they are", () => {
    show(card(SENSES.slice(0, 2)), "zh-CN");
    const [, second] = within(screen.getByTestId("review-senses")).getAllByRole("listitem");
    expect(second).toHaveTextContent("不及物machinery");
    // Nothing folded: the source sits under the senses.
    expect(screen.getByRole("link", { name: "来源：Simple English Wiktionary（CC BY-SA）" })).toBeVisible();
    expect(screen.getByTestId("review-more").querySelector("summary")).toHaveTextContent(
      "更多 · 1 条专业释义",
    );
  });

  it("falls back to ECDICT's definition without dictionary senses", () => {
    show(card([]));
    expect(screen.queryByTestId("review-senses")).not.toBeInTheDocument();
    expect(screen.getByTestId("review-more").querySelector("summary")).toHaveTextContent(
      "English definition",
    );
    expect(screen.getByText("a score in baseball")).toBeInTheDocument();
  });
});
