import { act, render, renderHook, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Card, Queue } from "@/lib/vocab";

import en from "../../../messages/en.json";
import { ReviewApp } from "./review-app";
import { useReviewSession } from "./use-review-session";

const api = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  api,
}));

const card = (id: number, spelling: string, overrides: Partial<Card> = {}): Card => ({
  word: {
    id,
    word: spelling,
    phonetic: "ˈæp(ə)l",
    translation: "n. 苹果\nn. 苹果树\n[医] 苹果",
    definition: "n. fruit with red or yellow\nor green skin",
  },
  source: "book",
  status: "learning",
  due: "2026-09-29T10:00:00Z",
  last_review: null,
  intervals: [60, 330, 600, 1_296_000],
  sentences: [
    {
      en: "Apples grow on apple trees.",
      zh: "苹果长在苹果树上。",
      source: "tatoeba",
      url: "https://tatoeba.org/sentences/show/7",
    },
  ],
  forms: [spelling, `${spelling}s`],
  ai_examples: [],
  ...overrides,
});

const queue = (reviews: Card[], fresh: Card[] = [], reviewsDue = reviews.length): Queue => ({
  reviews,
  new: fresh,
  reviews_due: reviewsDue,
  new_limit: 15,
  new_started: 0,
  book_id: "cet4",
});

const ids: Record<string, number> = { apple: 1, bread: 2, cheese: 3 };

const rated = (spelling: string) =>
  api.mock.calls.some(
    ([path, init]) =>
      path === "/vocab/reviews" &&
      (init as { json: { word_id: number } }).json.word_id === ids[spelling],
  );

function show(mode: "all" | "new" = "all") {
  return render(
    <NextIntlClientProvider locale="en" messages={en}>
      <ReviewApp mode={mode} />
    </NextIntlClientProvider>,
  );
}

beforeEach(() => api.mockReset());

describe("useReviewSession", () => {
  it("goes through reviews then new words, and asks again when it runs out", async () => {
    api
      .mockResolvedValueOnce(queue([card(1, "apple")], [card(2, "bread", { status: null })], 101))
      .mockResolvedValueOnce(card(1, "apple"))
      .mockResolvedValueOnce(card(2, "bread"))
      // Asked again: the new word failed a moment ago is due already.
      .mockResolvedValueOnce(queue([card(2, "bread")]))
      .mockResolvedValueOnce(card(2, "bread"))
      .mockResolvedValueOnce(queue([]));
    const { result } = renderHook(() => useReviewSession("all"));
    await waitFor(() => expect(result.current.current?.word.word).toBe("apple"));
    expect(api.mock.calls[0]![0]).toMatch(/^\/vocab\/queue\?mode=all/);
    // Two here and 100 more reviews beyond the first page.
    expect(result.current.remaining).toBe(102);

    await act(() => result.current.rate(3));
    expect(api).toHaveBeenCalledTimes(1); // not flipped yet: no rating

    act(() => result.current.flip());
    await act(() => result.current.rate(3));
    expect(api).toHaveBeenLastCalledWith("/vocab/reviews", {
      method: "POST",
      json: { word_id: 1, rating: 3, duration_ms: expect.any(Number) },
    });
    expect(result.current.current?.word.word).toBe("bread");
    expect(result.current.flipped).toBe(false);

    act(() => result.current.flip());
    await act(() => result.current.rate(1));
    expect(result.current.current?.word.word).toBe("bread");

    act(() => result.current.flip());
    await act(() => result.current.rate(3));
    expect(result.current.current).toBeNull();
    expect(result.current.loading).toBe(false);
    expect(result.current.reviewed).toBe(3);
  });

  it("keeps the card when saving a rating fails", async () => {
    api.mockResolvedValueOnce(queue([card(1, "apple")])).mockRejectedValueOnce(new Error("boom"));
    const { result } = renderHook(() => useReviewSession("all"));
    await waitFor(() => expect(result.current.current).not.toBeNull());
    act(() => result.current.flip());
    await act(() => result.current.rate(3));
    expect(result.current.error).toBeInstanceOf(Error);
    expect(result.current.current?.word.word).toBe("apple");
    expect(result.current.reviewed).toBe(0);
  });
});

describe("ReviewApp", () => {
  it("flips with Space and rates with the number keys", async () => {
    api
      .mockResolvedValueOnce(queue([card(1, "apple")], [card(3, "cheese", { status: null })]))
      .mockResolvedValueOnce(card(1, "apple"))
      .mockResolvedValueOnce(card(3, "cheese"))
      .mockResolvedValueOnce(queue([]));
    show();
    expect(await screen.findByRole("heading", { name: "apple" })).toBeInTheDocument();
    expect(screen.queryByTestId("review-back")).not.toBeInTheDocument();
    expect(screen.getByTestId("review-progress")).toHaveTextContent("Reviewed 0 · 2 to go");

    await userEvent.keyboard("3"); // not flipped: ignored
    expect(rated("apple")).toBe(false);
    await userEvent.keyboard(" ");
    const back = screen.getByTestId("review-back");
    expect(screen.getByTestId("review-card")).toHaveTextContent("/ˈæp(ə)l/");
    const meanings = within(back).getAllByRole("listitem").slice(0, 2);
    expect(meanings.map((li) => li.textContent)).toEqual(["n.苹果", "n.苹果树"]);
    // A real example under the meanings, the word in bold, linked to its source.
    const examples = screen.getByTestId("review-examples");
    expect(examples).toHaveTextContent("Apples grow on apple trees.苹果长在苹果树上。");
    expect([...examples.querySelectorAll("strong")].map((b) => b.textContent)).toEqual([
      "Apples",
      "apple",
    ]);
    expect(within(examples).getByRole("link", { name: "See this sentence on Tatoeba" })).toHaveAttribute(
      "href",
      "https://tatoeba.org/sentences/show/7",
    );
    expect(examples).toHaveTextContent("Source: Tatoeba");
    // Domain senses and the English definition wait under "More", wrapped lines joined.
    const more = screen.getByTestId("review-more");
    expect(more).not.toHaveAttribute("open");
    expect(more.querySelector("summary")).toHaveTextContent("More · 1 specialist sense · English definition");
    expect(more).toHaveTextContent("fruit with red or yellow or green skin");
    expect(more).toHaveTextContent("Source: ECDICT");
    expect(screen.getAllByTestId("rating-interval").map((e) => e.textContent)).toEqual([
      "1 min",
      "6 min",
      "10 min",
      "15 days",
    ]);

    await userEvent.keyboard("3");
    expect(await screen.findByRole("heading", { name: "cheese" })).toBeInTheDocument();
    expect(rated("apple")).toBe(true);
    expect(screen.getByText("New word")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Show answer" }));
    await userEvent.click(screen.getByRole("button", { name: /Easy/ }));
    expect(await screen.findByTestId("review-done")).toHaveTextContent(
      "Done for now: 2 cards reviewed.",
    );
  });

  it("writes AI examples only when asked", async () => {
    api.mockResolvedValueOnce(queue([card(1, "apple", { sentences: [] })])).mockResolvedValueOnce({
      sentences: [{ en: "An apple a day keeps the doctor away.", zh: "一天一苹果，医生远离我。" }],
      cefr: "A2",
    });
    show();
    await screen.findByRole("heading", { name: "apple" });
    await userEvent.keyboard(" ");
    expect(screen.getByTestId("review-examples")).not.toHaveTextContent("Source: Tatoeba");
    expect(api).toHaveBeenCalledTimes(1);

    await userEvent.click(screen.getByRole("button", { name: "AI examples" }));
    const ai = await screen.findByTestId("review-ai-examples");
    expect(api).toHaveBeenLastCalledWith("/vocab/words/1/examples", { method: "POST" });
    expect(ai).toHaveTextContent("An apple a day keeps the doctor away.");
    expect(ai.querySelector("strong")).toHaveTextContent("apple");
    expect(screen.getByTestId("review-examples")).toHaveTextContent("Written by AI");
    expect(screen.queryByRole("button", { name: "AI examples" })).not.toBeInTheDocument();
  });

  it("shows AI examples written ahead of time without asking", async () => {
    api.mockResolvedValueOnce(
      queue([
        card(1, "apple", {
          sentences: [],
          ai_examples: [{ en: "I ate an apple.", zh: "我吃了一个苹果。" }],
        }),
      ]),
    );
    show();
    await screen.findByRole("heading", { name: "apple" });
    await userEvent.keyboard(" ");
    expect(screen.getByTestId("review-ai-examples")).toHaveTextContent("I ate an apple.");
    expect(screen.getByTestId("review-examples")).toHaveTextContent("Written by AI");
    expect(screen.queryByRole("button", { name: "AI examples" })).not.toBeInTheDocument();
    expect(api).toHaveBeenCalledTimes(1);
  });

  it("in new-word mode, points to the reviews still due", async () => {
    api.mockResolvedValueOnce(queue([], [], 7));
    show("new");
    const done = await screen.findByTestId("review-done");
    expect(api.mock.calls[0]![0]).toMatch(/mode=new/);
    expect(done).toHaveTextContent("Nothing to review right now.");
    expect(done).toHaveTextContent("7 reviews are also due.");
    expect(screen.getByRole("link", { name: "Review now" })).toHaveAttribute(
      "href",
      "/vocab/review",
    );
  });
});
