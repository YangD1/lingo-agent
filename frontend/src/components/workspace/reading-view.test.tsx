import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { WorkspaceDocDetail } from "@/lib/workspace";

import en from "../../../messages/en.json";
import { ReadingView } from "./reading-view";

const api = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  api,
}));
vi.mock("@/lib/ai-usage", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/ai-usage")>()),
  loadEstimates: () => new Promise(() => {}),
}));
const shadowing = vi.hoisted(() => ({ mode: null as "assessment" | "rough" | null }));
vi.mock("@/lib/shadowing", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/shadowing")>()),
  useShadowingMode: () => shadowing.mode,
}));
vi.mock("@/components/speech/shadowing-panel", () => ({
  ShadowingPanel: ({ sentences, source, sourceId }: { sentences: string[]; source: string; sourceId?: string }) => (
    <div data-testid="shadowing-panel">{[source, sourceId ?? "-", ...sentences].join("|")}</div>
  ),
}));

const DOC: WorkspaceDocDetail = {
  id: "d1",
  conversation_id: "c1",
  kind: "reading",
  title: "The fox",
  source: "article",
  source_ref: "7",
  created_by: "learner",
  version: 1,
  truncated: false,
  created_at: "2026-10-15T00:00:00Z",
  updated_at: "2026-10-15T00:00:00Z",
  content: {
    paragraphs: ["The fox ran. It was fast.", "The dog slept all day.", "Then the rain came down."],
  },
  words: 15,
  versions: [],
};

const ANALYSIS = {
  main: "The fox ran.",
  clauses: [],
  phrases: [{ text: "ran", meaning: "跑（run 的过去式）" }],
  meaning: "狐狸跑了。",
  tip: "",
};

/** jsdom has no IntersectionObserver: the test says which paragraphs are in view. */
let observer: { callback: IntersectionObserverCallback; targets: Element[] } | null = null;

function inView(...paragraphs: number[]) {
  const current = observer;
  if (!current) throw new Error("nothing observed");
  act(() =>
    current.callback(
      current.targets.map(
        (target) =>
          ({
            target,
            isIntersecting: paragraphs.includes(Number((target as HTMLElement).dataset.paragraph)),
          }) as IntersectionObserverEntry,
      ),
      {} as IntersectionObserver,
    ),
  );
}

function show(doc: WorkspaceDocDetail = DOC) {
  return render(
    <NextIntlClientProvider locale="en" messages={en} timeZone="UTC">
      <ReadingView doc={doc} />
    </NextIntlClientProvider>,
  );
}

const translateCalls = () =>
  api.mock.calls.filter(([path]) => String(path).endsWith("/translate")).map(([, init]) => init.json.paragraphs);

beforeEach(() => {
  observer = null;
  globalThis.IntersectionObserver = class {
    constructor(callback: IntersectionObserverCallback) {
      observer = { callback, targets: [] };
    }
    observe(target: Element) {
      observer?.targets.push(target);
    }
    unobserve() {}
    disconnect() {}
    takeRecords() {
      return [];
    }
  } as unknown as typeof IntersectionObserver;
  api.mockImplementation((path: string, init: { json: { paragraphs: number[] } }) => {
    if (path.endsWith("/translate")) {
      return Promise.resolve({
        version: 1,
        translations: init.json.paragraphs.map((index) => ({ index, text: `译文 ${index}` })),
      });
    }
    if (path.endsWith("/analyze")) return Promise.resolve(ANALYSIS);
    return Promise.reject(new Error(`unexpected ${path}`));
  });
});

afterEach(() => {
  api.mockReset();
  shadowing.mode = null;
});

describe("ReadingView (ADR 0043 §4)", () => {
  it("shows the original with words to look up, and translates nothing", () => {
    show();
    const text = screen.getByTestId("workspace-text");
    expect(within(text).getByText("fox")).toHaveAttribute("data-word", "fox");
    expect(screen.queryByTestId("translation")).not.toBeInTheDocument();
    expect(api).not.toHaveBeenCalled();
  });

  it("translates the paragraphs in view, then the next ones as they scroll in", async () => {
    show();
    await userEvent.click(screen.getByRole("radio", { name: "Side by side" }));
    inView(0, 1);
    expect(await screen.findByText("译文 0")).toBeInTheDocument();
    expect(screen.getByText("译文 1")).toBeInTheDocument();
    expect(screen.getAllByTestId("translation-pending")).toHaveLength(1);
    // The original stays beside it.
    expect(screen.getByText("fox")).toBeInTheDocument();
    inView(1, 2);
    expect(await screen.findByText("译文 2")).toBeInTheDocument();
    expect(translateCalls()).toEqual([[0, 1], [2]]);
  });

  it("does not translate again when switching back and forth", async () => {
    show();
    await userEvent.click(screen.getByRole("radio", { name: "Translation" }));
    inView(0);
    expect(await screen.findByText("译文 0")).toBeInTheDocument();
    // Only the translation.
    expect(screen.queryByText("fox")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("radio", { name: "Original" }));
    await userEvent.click(screen.getByRole("radio", { name: "Side by side" }));
    inView(0);
    expect(screen.getByText("译文 0")).toBeInTheDocument();
    expect(translateCalls()).toEqual([[0]]);
  });

  it("says when a translation failed, and tries again", async () => {
    api.mockRejectedValueOnce(new Error("down"));
    show();
    await userEvent.click(screen.getByRole("radio", { name: "Side by side" }));
    inView(0);
    const failed = await screen.findByRole("alert");
    await userEvent.click(within(failed).getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("译文 0")).toBeInTheDocument();
    expect(translateCalls()).toEqual([[0], [0]]);
  });

  it("in the original, translates one paragraph under it on request, showing it is on the way", async () => {
    let answer: (value: unknown) => void = () => {};
    api.mockImplementationOnce(() => new Promise((resolve) => (answer = resolve)));
    show();
    const buttons = screen.getAllByRole("button", { name: "Translate this paragraph" });
    expect(buttons).toHaveLength(3);
    await userEvent.click(buttons[1]);
    expect(screen.getByTestId("translation-pending")).toHaveTextContent("Translating…");
    await act(async () => answer({ version: 1, translations: [{ index: 1, text: "译文 1" }] }));
    expect(screen.getByText("译文 1")).toBeInTheDocument();
    expect(screen.getAllByTestId("translation")).toHaveLength(1);
    expect(translateCalls()).toEqual([[1]]);

    // Hidden and shown again: kept, not asked for again.
    await userEvent.click(screen.getByRole("button", { name: "Hide this paragraph's translation" }));
    expect(screen.queryByText("译文 1")).not.toBeInTheDocument();
    await userEvent.click(screen.getAllByRole("button", { name: "Translate this paragraph" })[1]);
    expect(screen.getByText("译文 1")).toBeInTheDocument();
    expect(translateCalls()).toEqual([[1]]);
  });

  it("uses a paragraph translated in the original in the other displays", async () => {
    show();
    await userEvent.click(screen.getAllByRole("button", { name: "Translate this paragraph" })[0]);
    expect(await screen.findByText("译文 0")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("radio", { name: "Side by side" }));
    // The other displays show every translation: no button under each paragraph.
    expect(screen.queryByRole("button", { name: "Translate this paragraph" })).not.toBeInTheDocument();
    inView(0, 1);
    expect(await screen.findByText("译文 1")).toBeInTheDocument();
    expect(translateCalls()).toEqual([[0], [1]]);
    await userEvent.click(screen.getByRole("radio", { name: "Translation" }));
    inView(0, 1);
    expect(screen.getByText("译文 0")).toBeInTheDocument();
    expect(translateCalls()).toEqual([[0], [1]]);
  });

  it("in the original, says when a paragraph's translation failed, and tries again", async () => {
    api.mockRejectedValueOnce(new Error("down"));
    show();
    await userEvent.click(screen.getAllByRole("button", { name: "Translate this paragraph" })[2]);
    const failed = await screen.findByRole("alert");
    await userEvent.click(within(failed).getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("译文 2")).toBeInTheDocument();
    expect(translateCalls()).toEqual([[2], [2]]);
  });

  it("opens a sentence's analysis under it, several at once, and closes it again", async () => {
    show();
    await userEvent.click(screen.getByRole("button", { name: "Analyse sentences" }));
    // Words are not looked up in this mode: a tap means the sentence.
    expect(screen.getByTestId("workspace-text").querySelector("[data-word]")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "The fox ran." }));
    expect(api).toHaveBeenCalledWith("/workspace/docs/d1/analyze", {
      method: "POST",
      json: { paragraph: 0, sentence: "The fox ran." },
    });
    const card = await screen.findByTestId("sentence-analysis");
    expect(within(card).getByText("狐狸跑了。")).toBeInTheDocument();
    expect(within(card).getByText("ran")).toBeInTheDocument();
    // It sits between the sentence and the rest of the paragraph.
    expect(card.previousElementSibling).toHaveTextContent("The fox ran.");
    expect(card.nextElementSibling).toHaveTextContent("It was fast.");

    await userEvent.click(screen.getByRole("button", { name: "The dog slept all day." }));
    await waitFor(() => expect(screen.getAllByTestId("sentence-analysis")).toHaveLength(2));
    expect(api).toHaveBeenLastCalledWith("/workspace/docs/d1/analyze", {
      method: "POST",
      json: { paragraph: 1, sentence: "The dog slept all day." },
    });

    await userEvent.click(screen.getByRole("button", { name: "The fox ran." }));
    expect(screen.getAllByTestId("sentence-analysis")).toHaveLength(1);
  });

  it("says when an analysis failed, and tries again", async () => {
    api.mockRejectedValueOnce(new Error("down"));
    show();
    await userEvent.click(screen.getByRole("button", { name: "Analyse sentences" }));
    await userEvent.click(screen.getByRole("button", { name: "It was fast." }));
    const card = await screen.findByTestId("sentence-analysis");
    await userEvent.click(await within(card).findByRole("button", { name: "Try again" }));
    expect(await within(card).findByText("狐狸跑了。")).toBeInTheDocument();
  });

  it("shadows a paragraph, sentence by sentence, from the article it came from", async () => {
    shadowing.mode = "assessment";
    show();
    const mics = screen.getAllByRole("button", { name: "Shadow this paragraph" });
    expect(mics).toHaveLength(3);
    await userEvent.click(mics[0]);
    expect(screen.getByTestId("shadowing-panel")).toHaveTextContent("reading|7|The fox ran.|It was fast.");
  });

  describe("Markdown (task 84)", () => {
    const MD: WorkspaceDocDetail = {
      ...DOC,
      source: "paste",
      source_ref: null,
      content: {
        paragraphs: [
          "## Street trees",
          "- Trees give **shade** on [hot days](https://x.org).\n- They clean the air.",
          "```\nplant(tree)\n```",
          "| City | Trees |\n| --- | --- |\n| Paris | 100 |",
        ],
      },
    };

    it("shows headings, lists, bold, links, code and tables, with words to look up", () => {
      show(MD);
      const text = screen.getByTestId("workspace-text");
      expect(within(text).getByRole("heading", { level: 2 })).toHaveTextContent("Street trees");
      expect(within(text).getAllByRole("listitem")).toHaveLength(2);
      expect(within(text).getByText("shade").closest("strong")).not.toBeNull();
      expect(within(text).getByText("shade")).toHaveAttribute("data-word", "shade");
      expect(within(text).getByRole("link", { name: "hot days" })).toHaveAttribute("target", "_blank");
      expect(within(text).getByRole("table")).toHaveTextContent("Paris");
      // Code as it is: no words to look up, no translating it.
      const code = text.querySelector("pre");
      expect(code).toHaveTextContent("plant(tree)");
      expect(code?.querySelector("[data-word]")).toBeNull();
      expect(text.innerHTML).not.toContain("**");
      expect(screen.getAllByRole("button", { name: "Translate this paragraph" })).toHaveLength(3);
    });

    it("translates every block but code, and shows the translation as Markdown", async () => {
      api.mockImplementation((path: string, init: { json: { paragraphs: number[] } }) =>
        Promise.resolve({
          version: 1,
          translations: init.json.paragraphs.map((index) => ({ index, text: `- **译文** ${index}` })),
        }),
      );
      show(MD);
      await userEvent.click(screen.getByRole("radio", { name: "Side by side" }));
      // The code block is never watched, so never asked for.
      expect(observer?.targets).toHaveLength(3);
      inView(0, 1, 3);
      await waitFor(() => expect(screen.getAllByTestId("translation")).toHaveLength(3));
      expect(translateCalls()).toEqual([[0, 1, 3]]);
      const first = screen.getAllByTestId("translation")[0];
      expect(within(first).getByRole("listitem")).toHaveTextContent("译文 0");
      expect(within(first).getByText("译文").tagName).toBe("STRONG");
      // The code is still there, once.
      expect(screen.getAllByText("plant(tree)")).toHaveLength(1);
    });

    it("keeps headings and list items while sentences are analysed, without the inline marks", async () => {
      show(MD);
      await userEvent.click(screen.getByRole("button", { name: "Analyse sentences" }));
      const text = screen.getByTestId("workspace-text");
      expect(within(text).getByRole("heading", { level: 2 })).toHaveTextContent("Street trees");
      expect(text.querySelectorAll('[data-unit="item"]')).toHaveLength(2);
      expect(text.querySelector('[data-unit="item"]')).toHaveAttribute("data-marker", "•");
      // The table is not cut into sentences.
      expect(within(text).getByRole("table")).toBeInTheDocument();
      await userEvent.click(screen.getByRole("button", { name: "Trees give shade on hot days." }));
      expect(api).toHaveBeenCalledWith("/workspace/docs/d1/analyze", {
        method: "POST",
        json: { paragraph: 1, sentence: "Trees give shade on hot days." },
      });
      const card = await screen.findByTestId("sentence-analysis");
      // Under its own item, the next item after it.
      expect(card.parentElement).toHaveAttribute("data-unit", "item");
      expect(card.parentElement?.nextElementSibling).toHaveTextContent("They clean the air.");
    });
  });
});
