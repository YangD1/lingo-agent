import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import { markMistakes, paragraphs, type Submission, type WritingMistake } from "@/lib/writing";

import en from "../../../messages/en.json";
import { POLL_MS, WritingReview } from "./writing-review";

const api = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  api,
}));
const push = vi.hoisted(() => vi.fn());
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));

const KC = { id: "g.past_simple_regular", name_en: "Past simple", name_zh: "一般过去时", cefr: "A2" as const };

const mistake = (original: string, overrides: Partial<WritingMistake> = {}): WritingMistake => ({
  kc_id: KC.id,
  error_type: "wrong_form",
  severity: "medium",
  original,
  correction: "walked",
  explanation: "Use the past tense for yesterday.",
  ...overrides,
});

const done = (overrides: Partial<Submission> = {}): Submission => ({
  id: 7,
  prompt: "What did you do last weekend?",
  text: "Yesterday I walk to the park. It was fun.",
  word_count: 9,
  status: "done",
  error_code: null,
  corrections: [
    {
      index: 0,
      paragraph: 0,
      original: "Yesterday I walk to the park.",
      corrected: "Yesterday I walked to the park.",
      mistakes: [mistake("walk")],
    },
    { index: 1, paragraph: 0, original: "It was fun.", corrected: null, mistakes: [] },
  ],
  scores: {
    task: { score: 4, reason: "Answers the task." },
    coherence: { score: 3, reason: "Short." },
    vocabulary: { score: 3, reason: "Simple words." },
    grammar: { score: 2, reason: "Tense slips." },
  },
  summary: "A clear start; watch the past tense.",
  words: [
    { word_id: 1, word: "bench", added: true },
    { word_id: 2, word: "lake", added: false },
  ],
  model: "conn:fake-model",
  from_conversation: false,
  conversation_id: null,
  created_at: "2026-10-03T09:00:00Z",
  reviewed_at: "2026-10-03T09:00:20Z",
  kcs: [KC],
  ...overrides,
});

function show(id = 7) {
  return render(
    <NextIntlClientProvider locale="en" messages={en}>
      <WritingReview id={id} />
    </NextIntlClientProvider>,
  );
}

beforeEach(() => {
  api.mockReset();
  push.mockReset();
});

afterEach(() => vi.useRealTimers());

describe("markMistakes / paragraphs", () => {
  it("cuts a sentence around its mistakes, skipping overlaps and parts not found", () => {
    const pieces = markMistakes("He go to school and go home.", [
      mistake("go home"),
      mistake("go"),
      mistake("home."),
      mistake("missing"),
    ]);
    expect(pieces).toEqual([
      { text: "He ", mistake: null },
      { text: "go", mistake: 1 },
      { text: " to school and ", mistake: null },
      { text: "go home", mistake: 0 },
      { text: ".", mistake: null },
    ]);
  });

  it("groups sentences by paragraph, in order", () => {
    const s = (index: number, paragraph: number) => ({
      index,
      paragraph,
      original: `S${index}`,
      corrected: null,
      mistakes: [],
    });
    expect(paragraphs([s(2, 1), s(0, 0), s(1, 0)]).map((p) => p.map((x) => x.index))).toEqual([
      [0, 1],
      [2],
    ]);
  });
});

describe("WritingReview", () => {
  it("shows the review: sentences, explanations on demand, scores and words", async () => {
    api.mockResolvedValue(done());
    show();
    const user = userEvent.setup();

    expect(await screen.findByRole("heading", { name: "What did you do last weekend?" })).toBeInTheDocument();
    expect(screen.getByTestId("writing-summary")).toHaveTextContent(
      "1 grammar mistake, added to your learner model",
    );
    expect(screen.getByText("A clear start; watch the past tense.")).toBeInTheDocument();
    expect(screen.getAllByTestId("writing-score")).toHaveLength(4);
    expect(screen.getAllByTestId("writing-score")[3]).toHaveTextContent("Grammar2 / 5Tense slips.");
    expect(screen.getByText(/don't count towards mastery/)).toBeInTheDocument();
    expect(screen.getByText("bench")).toBeInTheDocument();
    expect(screen.getByText("lake")).toBeInTheDocument();

    const [wrong, fine] = screen.getAllByTestId("writing-sentence");
    expect(within(wrong).getByTestId("writing-corrected")).toHaveTextContent("Yesterday I walked to the park.");
    expect(fine).toHaveTextContent("It was fun.");
    expect(within(fine).queryByRole("button")).not.toBeInTheDocument();

    expect(screen.queryByTestId("writing-explanation")).not.toBeInTheDocument();
    await user.click(within(wrong).getByRole("button", { name: /Mistake: walk/ }));
    const explanation = screen.getByTestId("writing-explanation");
    expect(explanation).toHaveTextContent("walk → walked");
    expect(explanation).toHaveTextContent("Past simple");
    expect(explanation).toHaveTextContent("Use the past tense for yesterday.");
  });

  it("polls a review still running until it is done", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    api.mockResolvedValueOnce(done({ status: "pending", corrections: null, scores: null, summary: null }));
    api.mockResolvedValueOnce(done());
    show();

    expect(await screen.findByTestId("writing-pending")).toBeInTheDocument();
    await act(() => vi.advanceTimersByTimeAsync(POLL_MS));
    expect(await screen.findByTestId("writing-summary")).toBeInTheDocument();
    expect(api).toHaveBeenCalledTimes(2);
  });

  it("explains a failed review and offers to submit it again", async () => {
    api.mockResolvedValue(
      done({ status: "failed", error_code: "no_llm_configured", corrections: null }),
    );
    show();

    expect(await screen.findByTestId("writing-failed")).toHaveTextContent("No model is set up yet");
    expect(screen.getByRole("link", { name: "Submit again" })).toHaveAttribute(
      "href",
      "/writing?again=7",
    );
  });

  it("links back to the conversation it came from", async () => {
    api.mockResolvedValue(done({ from_conversation: true, conversation_id: "c-1" }));
    show();

    expect(await screen.findByRole("link", { name: /From a conversation/ })).toHaveAttribute(
      "href",
      "/chat?c=c-1",
    );
  });

  it("deletes after confirming, then goes back to the writing page", async () => {
    api.mockResolvedValueOnce(done());
    api.mockResolvedValueOnce(undefined);
    show();
    const user = userEvent.setup();

    await user.click(await screen.findByTestId("writing-delete"));
    expect(screen.getByText(/removed from your learner model too/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Delete" }));

    await waitFor(() => expect(push).toHaveBeenCalledWith("/writing"));
    expect(api).toHaveBeenLastCalledWith("/writing/7", { method: "DELETE" });
  });

  it("says when the writing doesn't exist", async () => {
    api.mockRejectedValue(new ApiError(404, "writing_not_found", "not found"));
    show(99);

    expect(await screen.findByText(/wasn't found/)).toBeInTheDocument();
  });
});
