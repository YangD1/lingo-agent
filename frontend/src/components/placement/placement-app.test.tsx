import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import type { Placement, PlacementResult, Question } from "@/lib/placement";

import en from "../../../messages/en.json";
import { PlacementApp } from "./placement-app";

const api = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  api,
}));

const vocab = (index: number, word: string): Question => ({
  id: `vocab-${index}`,
  stage: "vocab",
  index,
  total: 40,
  word,
});

const grammar: Question = {
  id: "grammar-0",
  stage: "grammar",
  index: 0,
  total: 20,
  stem: "She ___ to work every day.",
  options: ["go", "goes", "going", "gone"],
};

const result: PlacementResult = {
  cefr: "B1",
  vocab: { size: 3100, half_known_rank: 4000, false_alarm: 0.1, reliable: true, reference_cefr: "B1" },
  grammar: { ability: 0, standard_error: 0.6, cefr: "B1", answered: 20 },
};

const placement = (question: Question | null, done = false): Placement => ({
  id: "p1",
  status: done ? "done" : "in_progress",
  stage: question?.stage ?? "grammar",
  answered: 0,
  question,
  result: done ? result : null,
  created_at: "2026-09-30T00:00:00Z",
  finished_at: done ? "2026-09-30T00:10:00Z" : null,
});

function show() {
  return render(
    <NextIntlClientProvider locale="en" messages={en}>
      <PlacementApp />
    </NextIntlClientProvider>,
  );
}

beforeEach(() => api.mockReset());

describe("PlacementApp", () => {
  it("starts, answers by key and by click, and ends on the result", async () => {
    api
      .mockResolvedValueOnce(null) // latest: never tested
      .mockResolvedValueOnce(placement(vocab(0, "apple")))
      .mockResolvedValueOnce(placement(grammar))
      .mockResolvedValueOnce(placement(null, true));
    show();

    await userEvent.click(await screen.findByRole("button", { name: "Start" }));
    expect(api).toHaveBeenLastCalledWith("/placement", { method: "POST", json: { restart: false } });
    expect(await screen.findByText("apple")).toBeInTheDocument();
    expect(screen.getByTestId("placement-progress")).toHaveTextContent("Vocabulary · 1 of 40");

    await userEvent.keyboard("y");
    expect(api).toHaveBeenLastCalledWith("/placement/p1/answer", {
      method: "POST",
      json: { question_id: "vocab-0", yes: true },
    });

    await userEvent.click(await screen.findByRole("button", { name: /goes/ }));
    expect(api).toHaveBeenLastCalledWith("/placement/p1/answer", {
      method: "POST",
      json: { question_id: "grammar-0", choice: 1 },
    });
    expect(await screen.findByTestId("placement-level")).toHaveTextContent("B1");
  });

  it("picks up a test left halfway without the intro", async () => {
    api.mockResolvedValueOnce(placement(grammar));
    show();
    expect(await screen.findByTestId("placement-stem")).toHaveTextContent("She ___ to work");
    expect(screen.queryByTestId("placement-intro")).not.toBeInTheDocument();
  });

  it("sends one answer for a double press", async () => {
    let reply: (value: Placement) => void = () => {};
    api
      .mockResolvedValueOnce(placement(vocab(0, "apple")))
      .mockReturnValueOnce(new Promise<Placement>((resolve) => (reply = resolve)));
    show();
    await screen.findByText("apple");

    await userEvent.keyboard("nn");
    expect(api).toHaveBeenCalledTimes(2);
    reply(placement(vocab(1, "abide")));
    expect(await screen.findByText("abide")).toBeInTheDocument();
  });

  it("moves to the current question when this one was answered elsewhere", async () => {
    api
      .mockResolvedValueOnce(placement(vocab(0, "apple")))
      .mockRejectedValueOnce(new ApiError(409, "stale_question", "stale"))
      .mockResolvedValueOnce(placement(vocab(3, "zeal")));
    show();
    await screen.findByText("apple");

    await userEvent.keyboard("y");
    expect(await screen.findByText("zeal")).toBeInTheDocument();
    expect(api).toHaveBeenLastCalledWith("/placement/p1");
    expect(screen.getByRole("alert")).toHaveTextContent("out of date");
  });

  it("shows the result of a finished test", async () => {
    api.mockResolvedValueOnce(placement(null, true));
    show();
    expect(await screen.findByTestId("placement-level")).toHaveTextContent("B1");
  });
});
