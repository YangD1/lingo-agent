import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { useRef } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import type { Lookup } from "@/lib/vocab";

import en from "../../../messages/en.json";
import { Markdown } from "./markdown";
import { WordPopup, sentenceAround } from "./word-popup";

const api = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  api,
}));

const went: Lookup = {
  word: {
    id: 7,
    word: "go",
    phonetic: "gəʊ",
    translation: "v. 去\nv. 走\nv. 变得\nn. 尝试",
    definition: null,
  },
  matched: "lemma",
  on_list: false,
};

function Harness({ text }: { text: string }) {
  const ref = useRef<HTMLDivElement>(null);
  return (
    <div ref={ref}>
      <div data-role="assistant">
        <div data-slot="message">
          <Markdown words>{text}</Markdown>
        </div>
      </div>
      <WordPopup container={ref} />
    </div>
  );
}

function wrap(text: string) {
  return render(
    <NextIntlClientProvider locale="en" messages={en} timeZone="UTC">
      <Harness text={text} />
    </NextIntlClientProvider>,
  );
}

/** The backend by method and path. */
function backend(routes: Record<string, unknown>) {
  api.mockImplementation((path: string, init?: { method?: string }) => {
    const key = `${init?.method ?? "GET"} ${path.split("?")[0]}`;
    if (key in routes) {
      const value = routes[key];
      return value instanceof Error ? Promise.reject(value) : Promise.resolve(value);
    }
    return Promise.reject(new Error(`unexpected ${key}`));
  });
}

const word = (text: string) => {
  const span = document.querySelector<HTMLElement>(`[data-word="${text}"]`);
  if (!span) throw new Error(`no word ${text}`);
  return span;
};
const calls = (key: string) =>
  api.mock.calls.filter(([path, init]) => `${init?.method ?? "GET"} ${path.split("?")[0]}` === key);

beforeEach(() => {
  api.mockReset();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("Markdown words", () => {
  it("wraps the prose's English words, not code or links", () => {
    const { container } = render(
      <Markdown words>
        {"She **went** home, didn’t she? 好的 `print(x)` [docs](https://x.test)\n\n```\nfor i\n```"}
      </Markdown>,
    );
    const words = [...container.querySelectorAll("[data-word]")].map((s) => s.textContent);
    expect(words).toEqual(["She", "went", "home", "didn’t", "she"]);
    expect(container.textContent).toContain("She went home, didn’t she? 好的");
  });

  it("leaves words alone without `words`", () => {
    const { container } = render(<Markdown>{"She went home."}</Markdown>);
    expect(container.querySelector("[data-word]")).toBeNull();
  });
});

describe("sentenceAround", () => {
  it("cuts the word's sentence out of its paragraph", () => {
    const { container } = render(
      <Markdown words>{"It costs 3.5 dollars. Yesterday she **went** home! 很好。"}</Markdown>,
    );
    const span = container.querySelector('[data-word="went"]')!;
    expect(sentenceAround(span)).toEqual({ text: "Yesterday she went home!", at: 14 });
    const costs = container.querySelector('[data-word="costs"]')!;
    expect(sentenceAround(costs)?.text).toBe("It costs 3.5 dollars.");
  });
});

describe("WordPopup", () => {
  it("opens after hovering a word: entry, base form, sentence", async () => {
    backend({ "GET /vocab/lookup": went });
    wrap("Yesterday she went home. Then she slept.");
    await userEvent.hover(word("went"));

    const popup = await screen.findByTestId("word-popup");
    await waitFor(() => expect(popup).toHaveTextContent("/gəʊ/"));
    expect(calls("GET /vocab/lookup")[0][0]).toBe("/vocab/lookup?word=went");
    expect(popup).toHaveTextContent("Base form: go");
    // At most three lines of glosses.
    expect(screen.getByTestId("word-glosses").querySelectorAll("li")).toHaveLength(3);
    expect(screen.getByTestId("word-sentence")).toHaveTextContent("Yesterday she went home.");
    expect(screen.getByTestId("word-sentence").querySelector("strong")).toHaveTextContent("went");
    expect(screen.getByTestId("ai-badge-word_examples")).toBeInTheDocument();
  });

  it("doesn't open when the mouse just passes over", async () => {
    backend({ "GET /vocab/lookup": went });
    wrap("Yesterday she went home.");
    fireEvent.pointerOver(word("went"), { pointerType: "mouse" });
    fireEvent.pointerOut(word("went"), { pointerType: "mouse" });
    await new Promise((resolve) => setTimeout(resolve, 400));
    expect(screen.queryByTestId("word-popup")).not.toBeInTheDocument();
    expect(api).not.toHaveBeenCalled();
  });

  it("opens right away on a tap, and stays after the pointer leaves", async () => {
    backend({ "GET /vocab/lookup": went });
    wrap("Yesterday she went home.");
    await userEvent.click(word("went"));
    expect(await screen.findByTestId("word-popup")).toBeInTheDocument();
    fireEvent.pointerOut(word("went"), { pointerType: "mouse" });
    await new Promise((resolve) => setTimeout(resolve, 300));
    expect(screen.getByTestId("word-popup")).toBeInTheDocument();
  });

  it("closes when the mouse leaves a hovered word, and looks a word up once", async () => {
    backend({ "GET /vocab/lookup": went });
    wrap("Yesterday she went home.");
    await userEvent.hover(word("went"));
    await screen.findByTestId("word-popup");
    await userEvent.unhover(word("went"));
    await waitFor(() => expect(screen.queryByTestId("word-popup")).not.toBeInTheDocument());

    await userEvent.hover(word("went"));
    await screen.findByTestId("word-popup");
    expect(calls("GET /vocab/lookup")).toHaveLength(1);
  });

  it("adds the base form to the word list", async () => {
    backend({
      "GET /vocab/lookup": went,
      "POST /vocab/mine": { card: { word: went.word }, matched: "exact", added: true },
    });
    wrap("Yesterday she went home.");
    await userEvent.click(word("went"));
    await userEvent.click(await screen.findByRole("button", { name: "Add to my words" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Added to my words.");
    expect(calls("POST /vocab/mine")[0][1].json).toEqual({ word: "go" });
  });

  it("says when the word is already on the list", async () => {
    backend({ "GET /vocab/lookup": { ...went, on_list: true } });
    wrap("Yesterday she went home.");
    await userEvent.click(word("went"));
    expect(await screen.findByRole("status")).toHaveTextContent("On my word list.");
    expect(screen.queryByRole("button", { name: "Add to my words" })).not.toBeInTheDocument();
  });

  it("writes AI examples on request", async () => {
    backend({
      "GET /vocab/lookup": went,
      "POST /vocab/words/7/examples": {
        sentences: [{ en: "We go to school by bus.", zh: "我们坐公交上学。" }],
        cefr: "A2",
      },
    });
    wrap("Yesterday she went home.");
    await userEvent.click(word("went"));
    await userEvent.click(await screen.findByRole("button", { name: "AI examples" }));
    const list = await screen.findByTestId("word-examples");
    expect(list).toHaveTextContent("We go to school by bus.");
    expect(list).toHaveTextContent("我们坐公交上学。");
    expect(screen.queryByRole("button", { name: "AI examples" })).not.toBeInTheDocument();
  });

  it("says why examples couldn't be written", async () => {
    backend({
      "GET /vocab/lookup": went,
      "POST /vocab/words/7/examples": new ApiError(409, "no_llm_configured", "No chat model"),
    });
    wrap("Yesterday she went home.");
    await userEvent.click(word("went"));
    await userEvent.click(await screen.findByRole("button", { name: "AI examples" }));
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "AI examples" })).toBeEnabled();
  });

  it("says when the dictionary doesn't have the word", async () => {
    backend({ "GET /vocab/lookup": new ApiError(404, "word_not_found", "not found") });
    wrap("Ask Zorblax.");
    await userEvent.click(word("Zorblax"));
    expect(await screen.findByRole("alert")).toHaveTextContent(/./);
    expect(screen.queryByRole("button", { name: "Add to my words" })).not.toBeInTheDocument();
  });

  it("reads the word aloud when the browser can", async () => {
    const spoken: { text: string; lang: string }[] = [];
    vi.stubGlobal("speechSynthesis", {
      cancel: vi.fn(),
      speak: (u: { text: string; lang: string }) => spoken.push({ text: u.text, lang: u.lang }),
    });
    vi.stubGlobal(
      "SpeechSynthesisUtterance",
      class {
        lang = "";
        constructor(public text: string) {}
      },
    );
    backend({ "GET /vocab/lookup": went });
    wrap("Yesterday she went home.");
    await userEvent.click(word("went"));
    await act(async () => {
      await userEvent.click(await screen.findByRole("button", { name: "Read “go” aloud" }));
    });
    expect(spoken).toEqual([{ text: "go", lang: "en-US" }]);
  });
});
