import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Card, Queue } from "@/lib/vocab";

import en from "../../../messages/en.json";
import { ReviewDeck } from "./review-deck";

const api = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  api: (path: string, init?: unknown) =>
    path === "/speech/capabilities" ? Promise.resolve({ tts: false }) : api(path, init),
}));

const speech = vi.hoisted(() => ({ canSpeak: true, speakWord: vi.fn() }));
vi.mock("@/lib/speech", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/speech")>()),
  useCanSpeak: () => speech.canSpeak,
  speakWord: speech.speakWord,
}));

const card = (id: number, spelling: string, overrides: Partial<Card> = {}): Card => ({
  word: { id, word: spelling, phonetic: "ˈæp(ə)l", translation: "n. 苹果", definition: null },
  source: "book",
  status: "learning",
  due: "2026-10-11T10:00:00Z",
  last_review: "2026-10-10T10:00:00Z",
  intervals: [60, 330, 600, 1_296_000],
  sentences: [],
  forms: [spelling],
  ai_examples: [],
  gloss: "n. 苹果",
  choices: ["n. 香蕉", "n. 面包", "n. 奶酪"],
  ...overrides,
});

const queue = (reviews: Card[], fresh: Card[] = []): Queue => ({
  reviews,
  new: fresh,
  reviews_due: reviews.length,
  new_limit: 15,
  new_started: 0,
  book_id: "cet4",
});

const empty = queue([]);

function show() {
  return render(
    <NextIntlClientProvider locale="en" messages={en}>
      <ReviewDeck mode="all" onClose={() => {}} onReviewAll={() => {}} />
    </NextIntlClientProvider>,
  );
}

const lastReview = () =>
  api.mock.calls.findLast(([path]) => path === "/vocab/reviews")?.[1] as
    | { json: { word_id: number; rating: number; format: string } }
    | undefined;

beforeEach(() => {
  api.mockReset();
  speech.canSpeak = true;
  speech.speakWord.mockReset();
  window.localStorage.clear();
});

describe("ReviewDeck card types (task 63)", () => {
  it("reads the word, takes a picked meaning and suggests a rating", async () => {
    window.localStorage.setItem("lingo.vocab.reviewFormat", "listen");
    api.mockResolvedValueOnce(queue([card(1, "apple")])).mockResolvedValue(card(1, "apple"));
    const user = userEvent.setup();
    show();

    const options = within(await screen.findByRole("group", { name: "Pick the meaning" }));
    // The word stays hidden; it is read aloud as the card shows.
    expect(screen.queryByRole("heading", { name: "apple" })).toBeNull();
    // Read from an effect, which can run just after the options appear.
    await waitFor(() => expect(speech.speakWord).toHaveBeenCalledWith("apple"));
    await user.click(screen.getByRole("button", { name: "Play again" }));
    expect(speech.speakWord).toHaveBeenCalledTimes(2);
    expect(options.getAllByRole("button")).toHaveLength(4);

    await user.click(options.getByRole("button", { name: /香蕉/ }));
    expect(screen.getByTestId("review-result")).toHaveTextContent("Wrong");
    expect(screen.getByTestId("review-result")).toHaveTextContent("You picked “n. 香蕉”");
    expect(screen.getByRole("heading", { name: "apple" })).toBeInTheDocument();
    // A wrong pick suggests Again; Enter takes it.
    const again = screen.getByRole("button", { name: /Again/ });
    expect(again).toHaveAttribute("data-suggested");
    expect(again).toHaveTextContent("Suggested");
    await user.keyboard("{Enter}");
    await waitFor(() =>
      expect(lastReview()?.json).toMatchObject({ word_id: 1, rating: 1, format: "listen" }),
    );
  });

  it("picks with the number keys and lets the learner rate differently", async () => {
    window.localStorage.setItem("lingo.vocab.reviewFormat", "listen");
    api.mockResolvedValueOnce(queue([card(1, "apple")])).mockResolvedValue(empty);
    const user = userEvent.setup();
    show();

    const options = within(await screen.findByRole("group", { name: "Pick the meaning" }));
    const place = options.getAllByRole("button").findIndex((b) => b.textContent?.includes("苹果"));
    await user.keyboard(String(place + 1));
    expect(screen.getByTestId("review-result")).toHaveTextContent("Right");
    expect(screen.getByRole("button", { name: /Good/ })).toHaveAttribute("data-suggested");
    await user.keyboard("4");
    await waitFor(() => expect(lastReview()?.json).toMatchObject({ rating: 4, format: "listen" }));
  });

  it("judges a spelling and marks the letters missed", async () => {
    window.localStorage.setItem("lingo.vocab.reviewFormat", "spell");
    api.mockResolvedValueOnce(queue([card(1, "apple")])).mockResolvedValue(empty);
    const user = userEvent.setup();
    show();

    // The meaning and the sound, not the word.
    await screen.findByTestId("review-spell");
    expect(screen.getByText("n. 苹果")).toBeInTheDocument();
    expect(screen.queryByText(/ˈæp/)).toBeNull();
    expect(screen.getByRole("button", { name: "Can't spell it" })).toBeInTheDocument();
    await user.type(screen.getByRole("textbox", { name: "Type the word" }), "aple{Enter}");

    const result = screen.getByTestId("review-result");
    expect(result).toHaveTextContent("One letter off");
    expect(result).toHaveTextContent("You wrote: aple");
    expect(screen.getByRole("button", { name: /Hard/ })).toHaveAttribute("data-suggested");
    await user.click(screen.getByRole("button", { name: /Hard/ }));
    await waitFor(() => expect(lastReview()?.json).toMatchObject({ rating: 2, format: "spell" }));
  });

  it("takes a right spelling as Good, and giving up as Again", async () => {
    window.localStorage.setItem("lingo.vocab.reviewFormat", "spell");
    api
      .mockResolvedValueOnce(queue([card(1, "apple"), card(2, "bread", { gloss: "n. 面包" })]))
      .mockResolvedValueOnce(card(1, "apple"))
      .mockResolvedValue(empty);
    const user = userEvent.setup();
    show();

    await user.type(await screen.findByRole("textbox", { name: "Type the word" }), " Apple {Enter}");
    expect(screen.getByTestId("review-result")).toHaveTextContent("Spelled right");
    await user.keyboard("{Enter}");
    await waitFor(() => expect(lastReview()?.json).toMatchObject({ word_id: 1, rating: 3 }));

    await user.click(await screen.findByRole("button", { name: "Can't spell it" }));
    expect(screen.getByTestId("review-result")).toHaveTextContent("Not written");
    expect(screen.getByRole("button", { name: /Again/ })).toHaveAttribute("data-suggested");
  });

  it("shows new words, and words without wrong meanings, as words, and says why", async () => {
    window.localStorage.setItem("lingo.vocab.reviewFormat", "listen");
    api
      .mockResolvedValueOnce(
        queue([card(1, "apple", { choices: [] })], [card(2, "bread", { last_review: null })]),
      )
      .mockResolvedValueOnce(card(1, "apple"))
      .mockResolvedValue(empty);
    const user = userEvent.setup();
    show();

    expect(await screen.findByRole("heading", { name: "apple" })).toBeInTheDocument();
    expect(screen.getByTestId("review-format-note")).toHaveTextContent("four distinct meanings");
    await user.keyboard(" 3");
    await waitFor(() => expect(lastReview()?.json).toMatchObject({ format: "recognize" }));
    expect(await screen.findByRole("heading", { name: "bread" })).toBeInTheDocument();
    expect(screen.getByTestId("review-format-note")).toHaveTextContent("first time");
  });

  it("switches the card type and remembers it; without speech only words", async () => {
    api.mockResolvedValue(queue([card(1, "apple")]));
    const user = userEvent.setup();
    const { unmount } = show();

    expect(await screen.findByRole("heading", { name: "apple" })).toBeInTheDocument();
    await user.click(screen.getByRole("radio", { name: "Spell" }));
    expect(screen.getByTestId("review-spell")).toBeInTheDocument();
    expect(window.localStorage.getItem("lingo.vocab.reviewFormat")).toBe("spell");
    unmount();

    speech.canSpeak = false;
    show();
    expect(await screen.findByRole("heading", { name: "apple" })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Listen" })).toBeDisabled();
    expect(screen.getByTestId("review-format-note")).toHaveTextContent("Nothing on this device");
  });
});
