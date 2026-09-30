import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Advice, AdviceItem } from "@/lib/advice";
import { ApiError } from "@/lib/api";

import en from "../../../messages/en.json";
import zh from "../../../messages/zh-CN.json";
import { AdviceCard, templateKey } from "./advice-card";

const api = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  api,
}));

const item = (over: Partial<AdviceItem>): AdviceItem => ({
  candidate_id: over.kind ?? "vocab_review",
  kind: "vocab_review",
  title: null,
  reason: null,
  count: null,
  days_since: null,
  in_progress: false,
  kc: null,
  p_mastery: null,
  book: null,
  ...over,
});

const KC = { id: "g.third", name_en: "Third person -s", name_zh: "第三人称单数", cefr: "A1" } as const;

const advice = (over: Partial<Advice>): Advice => ({
  items: [],
  status: "ai",
  generated_at: "2026-09-30T04:00:00Z",
  refreshing: false,
  refresh_after: null,
  ...over,
});

function show(locale: "en" | "zh-CN" = "en") {
  return render(
    <NextIntlClientProvider locale={locale} messages={locale === "en" ? en : zh} timeZone="UTC">
      <AdviceCard />
    </NextIntlClientProvider>,
  );
}

beforeEach(() => api.mockReset());
afterEach(() => vi.useRealTimers());

describe("templateKey", () => {
  it("tells a first test, a retest and one left halfway apart", () => {
    expect(templateKey(item({ kind: "placement" }))).toBe("placement");
    expect(templateKey(item({ kind: "placement", days_since: 70 }))).toBe("retest");
    expect(templateKey(item({ kind: "placement", days_since: 70, in_progress: true }))).toBe(
      "resume",
    );
    expect(templateKey(item({ kind: "vocab_learn" }))).toBe("vocab_learn");
  });
});

describe("AdviceCard", () => {
  it("writes template advice with live numbers and links to each action", async () => {
    api.mockResolvedValueOnce(
      advice({
        status: "no_model",
        items: [
          item({ kind: "placement", days_since: 75 }),
          item({ kind: "vocab_review", count: 12 }),
          item({
            kind: "grammar_practice",
            candidate_id: "grammar_practice:g.third",
            count: 3,
            kc: KC,
            p_mastery: 0.23,
          }),
        ],
      }),
    );
    show();

    const items = await screen.findAllByTestId("advice-item");
    expect(api.mock.calls[0][0]).toMatch(/^\/advice\?locale=en/);
    expect(items.map((i) => i.dataset.kind)).toEqual(["placement", "vocab_review", "grammar_practice"]);
    expect(items[0]).toHaveTextContent("Retake the placement test");
    expect(items[0]).toHaveTextContent("Last taken 75 days ago");
    expect(within(items[0]).getByRole("link")).toHaveAttribute("href", "/placement");
    expect(items[1]).toHaveTextContent("12 due");
    expect(within(items[1]).getByRole("link", { name: "Review" })).toHaveAttribute(
      "href",
      "/vocab/review",
    );
    expect(items[2]).toHaveTextContent("Practise: Third person -s");
    expect(items[2]).toHaveTextContent("Third person -s · 3 mistakes lately · mastery 23%");
    // Until task 19's practice chat, grammar leads to the evidence in the learner model.
    expect(within(items[2]).getByRole("link", { name: "See why" })).toHaveAttribute(
      "href",
      "/learner?kc=g.third",
    );
    expect(screen.queryByText("AI")).not.toBeInTheDocument();
    expect(
      within(screen.getByTestId("advice-status")).getByRole("link", { name: "Open settings" }),
    ).toHaveAttribute("href", "/settings");
  });

  it("marks the model's advice and keeps its text", async () => {
    api.mockResolvedValueOnce(
      advice({
        items: [
          item({ kind: "vocab_learn", count: 5, title: "趁热学新词", reason: "为雅思攒词汇。" }),
          item({ kind: "choose_book" }),
        ],
      }),
    );
    show("zh-CN");

    const items = await screen.findAllByTestId("advice-item");
    expect(api.mock.calls[0][0]).toMatch(/locale=zh-CN/);
    expect(items[0]).toHaveTextContent("趁热学新词");
    expect(items[0]).toHaveTextContent("为雅思攒词汇。");
    expect(items[0]).toHaveTextContent("今天还剩 5 个新词");
    expect(within(items[0]).getByText("AI")).toBeInTheDocument();
    expect(items[1]).toHaveTextContent("选一本词书");
    expect(within(items[1]).queryByText("AI")).not.toBeInTheDocument();
    expect(screen.getByText(/由 AI 从学习引擎给出的候选里挑选/)).toBeInTheDocument();
  });

  it("asks again while new advice is being written", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    api
      .mockResolvedValueOnce(
        advice({ status: null, refreshing: true, items: [item({ kind: "placement" })] }),
      )
      .mockResolvedValueOnce(
        advice({ items: [item({ kind: "placement", title: "Find your level", reason: "Why" })] }),
      );
    show();
    expect(await screen.findByTestId("advice-status")).toHaveTextContent("Writing your advice");
    expect(screen.getByRole("button", { name: "Refresh advice" })).toBeDisabled();

    await vi.advanceTimersByTimeAsync(3000);

    expect(await screen.findByText("Find your level")).toBeInTheDocument();
    expect(api).toHaveBeenCalledTimes(2);
  });

  it("refreshes by hand, at most once an hour", async () => {
    api
      .mockResolvedValueOnce(advice({ items: [item({ kind: "choose_book" })] }))
      .mockRejectedValueOnce(new ApiError(429, "advice_refresh_limited", "limited"));
    show();
    await userEvent.click(await screen.findByRole("button", { name: "Refresh advice" }));

    expect(api.mock.calls[1][0]).toMatch(/^\/advice\/refresh\?/);
    expect(api.mock.calls[1][1]).toEqual({ method: "POST" });
    expect(await screen.findByRole("alert")).toHaveTextContent("once an hour");
    // The advice already shown stays.
    expect(screen.getByTestId("advice-item")).toHaveTextContent("Choose a word book");
  });

  it("says when to refresh again", async () => {
    const later = new Date(Date.now() + 39.5 * 60_000).toISOString();
    api.mockResolvedValueOnce(advice({ refresh_after: later }));
    show();
    expect(await screen.findByText("Can refresh again in 40 min")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Refresh advice" })).toBeDisabled();
    expect(screen.getByRole("link", { name: "A chat with your tutor" })).toHaveAttribute(
      "href",
      "/chat",
    );
  });
});
