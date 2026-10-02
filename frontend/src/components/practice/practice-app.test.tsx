import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import type { Item, Origin, PracticeSet, SetBrief } from "@/lib/practice";

import en from "../../../messages/en.json";
import { PracticeApp } from "./practice-app";

const api = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  api,
}));
vi.mock("@/lib/ai-usage", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/ai-usage")>()),
  loadEstimates: () => new Promise(() => {}),
}));

const KC = { id: "g.third", name_en: "Third person -s", name_zh: "第三人称单数", cefr: "A1" as const };

const choice: Item = {
  id: 1,
  position: 0,
  kc: KC,
  format: "choice4",
  content: { stem: "He ___ here.", options: ["live", "lives", "living", "is live"] },
  status: "ok",
  from_bank: true,
  answer: null,
  result: null,
};

const findFix: Item = {
  ...choice,
  id: 2,
  position: 1,
  format: "find_fix",
  from_bank: false,
  content: { segments: ["He ", "go ", "to work."] },
};

const translate: Item = {
  ...choice,
  id: 3,
  position: 2,
  format: "translate",
  from_bank: false,
  content: { source: "她走路上班。" },
};

const set = (overrides: Partial<PracticeSet> = {}): PracticeSet => ({
  id: "s1",
  status: "ready",
  stage: null,
  origin: "practice",
  focus_kc: null,
  error_code: null,
  created_at: "2026-10-02T09:00:00Z",
  started_at: "2026-10-02T09:00:00Z",
  finished_at: null,
  items: [choice, findFix, translate],
  how_made: { written: 2, from_bank: 1, rejected: 1, writers: ["deepseek:chat"], reviewers: ["qwen:max"] },
  summary: null,
  ...overrides,
});

const answered = (item: Item, correct: boolean, response: Record<string, unknown>): Item => ({
  ...item,
  answer: { correct: "lives", accepted: ["goes "], wrong_segment: 1, explanation: "Third person takes -s." },
  result: {
    correct,
    response,
    feedback: { explanation: "Third person takes -s.", corrected: null, other_mistakes: [], model: null },
    created_at: "2026-10-02T09:01:00Z",
  },
});

function show(from: Origin | null = null, kc: string | null = null) {
  return render(
    <NextIntlClientProvider locale="en" messages={en} timeZone="UTC">
      <PracticeApp from={from} kc={kc} />
    </NextIntlClientProvider>,
  );
}

beforeEach(() => {
  api.mockReset();
});

describe("PracticeApp", () => {
  it("lists recent sets and starts a new one, showing progress while it is written", async () => {
    const recent: SetBrief[] = [
      {
        id: "old",
        status: "done",
        origin: "learner",
        focus_kc: KC,
        created_at: "2026-10-01T09:00:00Z",
        finished_at: "2026-10-01T09:10:00Z",
        total: 10,
        answered: 10,
        correct: 8,
      },
    ];
    api
      .mockResolvedValueOnce(recent)
      .mockResolvedValueOnce(set({ status: "generating", stage: "reviewing", items: [] }))
      .mockResolvedValueOnce(set());
    show();

    const row = await screen.findByTestId("practice-recent");
    expect(row).toHaveTextContent("Third person -s");
    expect(row).toHaveTextContent("8 / 10 right");
    await userEvent.click(screen.getByRole("button", { name: "Start a set" }));
    expect(api).toHaveBeenCalledWith("/practice/sets", {
      method: "POST",
      json: { origin: "practice", kc_id: null },
    });
    expect(await screen.findByTestId("practice-generating")).toBeInTheDocument();
    expect(await screen.findByRole("status", { name: "Checking questions…" })).toBeInTheDocument();

    // Polled until ready.
    expect(await screen.findByTestId("practice-item", {}, { timeout: 3000 })).toBeInTheDocument();
    expect(api).toHaveBeenLastCalledWith("/practice/sets/s1");
  });

  it("offers to continue an unfinished set", async () => {
    api.mockResolvedValueOnce([
      {
        id: "s1",
        status: "in_progress",
        origin: "practice",
        focus_kc: null,
        created_at: "2026-10-02T09:00:00Z",
        finished_at: null,
        total: 10,
        answered: 4,
        correct: 3,
      },
    ] satisfies SetBrief[]);
    show();
    expect(await screen.findByRole("button", { name: "Continue your last set" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Continue (4/10)" })).toBeInTheDocument();
  });

  it("answers by key, shows the verdict, and goes on with Enter", async () => {
    api
      .mockResolvedValueOnce(set({ focus_kc: KC, origin: "learner" }))
      .mockResolvedValueOnce({ item: answered(choice, false, { choice: "live" }), set_done: false });
    show("learner", "g.third");

    expect(await screen.findByTestId("practice-focus")).toHaveTextContent("Third person -s");
    expect(api).toHaveBeenCalledWith("/practice/sets", {
      method: "POST",
      json: { origin: "learner", kc_id: "g.third" },
    });
    expect(screen.getByText("From the bank")).toBeInTheDocument();
    await userEvent.keyboard("1");
    const call = api.mock.calls[1];
    expect(call[0]).toBe("/practice/exercises/1/answer");
    expect(call[1].json).toMatchObject({ choice: "live" });
    expect(call[1].json.latency_ms).toBeGreaterThanOrEqual(0);

    const verdict = await screen.findByTestId("practice-verdict");
    expect(verdict).toHaveAttribute("data-correct", "false");
    expect(verdict).toHaveTextContent("Your answer: live");
    expect(verdict).toHaveTextContent("Answer: lives");
    expect(verdict).toHaveTextContent("Third person takes -s.");

    await userEvent.keyboard("{Enter}");
    expect(await screen.findByTestId("practice-segments")).toBeInTheDocument();
  });

  it("finds the wrong piece, then fixes it keeping its spacing", async () => {
    api
      .mockResolvedValueOnce(set({ items: [answered(choice, true, { choice: "lives" }), findFix] }))
      .mockResolvedValueOnce({
        item: answered(findFix, true, { segment: 1, fix: "goes " }),
        set_done: false,
      });
    show("dashboard");

    await userEvent.click(await screen.findByRole("button", { name: "Part 2: go" }));
    const input = screen.getByRole("textbox", { name: "Change it to" });
    expect(input).toHaveValue("go");
    await userEvent.clear(input);
    await userEvent.type(input, "goes{Enter}");
    expect(api.mock.calls[1][1].json).toMatchObject({ segment: 1, fix: "goes " });
    expect(await screen.findByTestId("practice-verdict")).toHaveTextContent("Correct");
  });

  it("keeps a written answer when grading fails, so it can be sent again", async () => {
    api
      .mockResolvedValueOnce(
        set({
          items: [
            answered(choice, true, { choice: "lives" }),
            answered(findFix, true, { segment: 1, fix: "goes " }),
            translate,
          ],
        }),
      )
      .mockRejectedValueOnce(new ApiError(503, "grading_failed", "could not grade"))
      .mockResolvedValueOnce({
        item: answered(translate, true, { text: "She walks to work." }),
        set_done: true,
      })
      .mockResolvedValueOnce(
        set({
          status: "done",
          summary: {
            total: 3,
            correct: 3,
            kcs: [
              {
                kc: KC,
                items: 3,
                correct: 3,
                before: { p_mastery: 0.3, state: "weak", learned: false },
                after: { p_mastery: 0.62, state: "learning", learned: false },
                progress: null,
              },
            ],
          },
        }),
      );
    show("dashboard");

    const box = await screen.findByRole("textbox", { name: "Your translation" });
    await userEvent.type(box, "She walks to work.{Enter}");
    expect(await screen.findByText(/Grading failed/)).toBeInTheDocument();
    expect(box).toHaveValue("She walks to work.");
    await userEvent.click(screen.getByRole("button", { name: "Submit" }));

    await userEvent.click(await screen.findByRole("button", { name: "See results" }));
    const summary = await screen.findByTestId("practice-summary");
    expect(within(summary).getByTestId("practice-score")).toHaveTextContent("3 of 3 right");
    expect(within(summary).getByTestId("practice-kc-g.third")).toHaveTextContent("30%");
    expect(within(summary).getByTestId("practice-kc-g.third")).toHaveTextContent("62%");
    expect(within(summary).getByTestId("practice-made-by")).toHaveTextContent(
      "2 written by deepseek:chat, checked by qwen:max; 1 from the question bank; 1 rejected in review",
    );
  });

  it("reports a faulty item", async () => {
    api
      .mockResolvedValueOnce(set())
      .mockResolvedValueOnce({
        item: { ...choice, status: "reported", answer: { correct: "lives", explanation: "x" } },
        set_done: false,
      });
    show("dashboard");

    await userEvent.click(await screen.findByRole("button", { name: "Report a problem" }));
    const ask = screen.getByRole("group", { name: /Report this question as faulty/ });
    await userEvent.click(within(ask).getByRole("button", { name: "Report" }));
    expect(api).toHaveBeenCalledWith("/practice/exercises/1/report", { method: "POST", json: {} });
    expect(await screen.findByTestId("practice-reported")).toBeInTheDocument();
    expect(screen.getByTestId("practice-next")).toBeInTheDocument();
  });

  it("says why a set could not be made", async () => {
    api.mockResolvedValueOnce(set({ status: "failed", error_code: "no_llm_configured", items: [] }));
    show("dashboard");
    expect(await screen.findByTestId("practice-failed")).toHaveTextContent("No model is set up");
  });
});
