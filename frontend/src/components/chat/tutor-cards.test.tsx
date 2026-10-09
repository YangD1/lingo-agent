import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import type { TutorCard } from "@/lib/cards";

import zh from "../../../messages/zh-CN.json";
import { TutorCards } from "./tutor-cards";

vi.mock("@/lib/ai-usage", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/ai-usage")>()),
  loadEstimates: () => new Promise(() => {}),
}));

const card = (overrides: Partial<TutorCard>): TutorCard => ({
  id: "k1",
  turn_id: "u1",
  kind: "word_book",
  params: { book_id: "ielts", daily_new: 20 },
  status: "proposed",
  display: { book: { id: "ielts", name_en: "IELTS", name_zh: "雅思" } },
  created_at: null,
  decided_at: null,
  undone_at: null,
  ...overrides,
});

function show(cards: TutorCard[], onDecide = vi.fn(async () => {})) {
  render(
    <NextIntlClientProvider locale="zh-CN" messages={zh}>
      <TutorCards cards={cards} onDecide={onDecide} />
    </NextIntlClientProvider>,
  );
  return onDecide;
}

describe("TutorCards", () => {
  it("asks before changing the word book", async () => {
    const proposal = card({});
    const onDecide = show([proposal]);
    expect(screen.getByText("把词书换成 雅思")).toBeInTheDocument();
    expect(screen.getByText("每天 20 个新词")).toBeInTheDocument();
    expect(screen.getByText("你确认之前不会有任何改动。")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "确认" }));
    expect(onDecide).toHaveBeenCalledWith(proposal, "apply");
    await userEvent.click(screen.getByRole("button", { name: "不用了" }));
    expect(onDecide).toHaveBeenLastCalledWith(proposal, "decline");
  });

  it("undoes an applied card, and says why it can't", async () => {
    const applied = card({ status: "applied" });
    const onDecide = show(
      [applied],
      vi.fn(async () => {
        throw new ApiError(409, "setting_changed", "changed since");
      }),
    );
    expect(screen.getByText("已完成。")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "撤销" }));
    expect(onDecide).toHaveBeenCalledWith(applied, "undo");
    expect(await screen.findByRole("alert")).toHaveTextContent("你之后又改过这项设置");
  });

  it("shows the goal's fields, practice and page shortcuts", () => {
    show([
      card({
        id: "k1",
        kind: "learning_goal",
        params: { goal: "考雅思 7 分", target_exam: "ielts", daily_minutes: 30 },
        status: "undone",
        display: {},
      }),
      card({
        id: "k2",
        kind: "practice",
        params: { kc_id: "g.third" },
        status: "info",
        display: { kc: { id: "g.third", name_en: "Third person -s", name_zh: "第三人称单数", cefr: "A1" } },
      }),
      card({
        id: "k3",
        kind: "link",
        params: { kind: "vocab_review" },
        status: "info",
        display: {},
        live: { reviews_due: 12, new_left: 5 },
      }),
    ]);
    expect(screen.getByText("考雅思 7 分")).toBeInTheDocument();
    expect(screen.getByText("雅思")).toBeInTheDocument();
    expect(screen.getByText("30 分钟")).toBeInTheDocument();
    expect(screen.getByText("已撤销，恢复成原来的设置。")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "撤销" })).toBeNull();
    expect(screen.getByRole("link", { name: "做一组题" })).toHaveAttribute(
      "href",
      "/practice?from=card&kc=g.third",
    );
    expect(screen.getByRole("link", { name: "对话练习" })).toHaveAttribute(
      "href",
      "/chat?practice=g.third",
    );
    expect(screen.getByText("练习 第三人称单数 (A1)")).toBeInTheDocument();
    expect(screen.getByTestId("card-live")).toHaveTextContent("待复习 12 个 · 今天还剩 5 个新词");
    expect(screen.getByRole("link", { name: "去复习" })).toHaveAttribute("href", "/vocab/review");
  });

  it("links writing_coach's review, and skips kinds it doesn't know", () => {
    show([
      card({ id: "w1", kind: "writing", params: { submission_id: 7 }, status: "info" }),
      card({ id: "x1", kind: "future_kind" as TutorCard["kind"], status: "info" }),
    ]);
    expect(screen.getByText("作文批改")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "查看逐句批改" })).toHaveAttribute("href", "/writing/7");
    expect(screen.getAllByTestId("tutor-card")).toHaveLength(1);
  });

  it("lets the learner adjust the tutor's plan before confirming it", async () => {
    const params = {
      plan_id: "p1",
      day: "2026-10-09",
      choice: { review: 0, new_words: 0, practice: false, reading: false, writing: true },
      items: [{ kind: "writing", minutes: 15, count: null, ref: null }],
      minutes: 15,
      limits: { reviews_due: 8, new_left: 0, practice: true, reading: false, max_count: 500 },
      estimates: { review: 0.25, new_words: 1, practice: 8, reading: 10, writing: 15 },
    };
    const proposal = card({ id: "p", kind: "daily_plan", params, display: {} });
    const onDecide = show([proposal]);
    expect(screen.getByText("新的今天计划")).toBeInTheDocument();
    await userEvent.click(
      screen.getByRole("button", { name: "复习 0 个词：增加" }),
    );
    await userEvent.click(screen.getByRole("button", { name: "确认" }));
    expect(onDecide).toHaveBeenCalledWith(proposal, "apply", {
      ...params.choice,
      review: 5,
    });
  });

  it("lists an answered plan card's items", () => {
    show([
      card({
        id: "p",
        kind: "daily_plan",
        status: "applied",
        params: {
          choice: {},
          items: [
            { kind: "review", minutes: 2, count: 8, ref: null },
            { kind: "practice", minutes: 8, count: null, ref: "g.third" },
          ],
          minutes: 10,
        },
        display: { kc: { id: "g.third", name_en: "Third person -s", name_zh: "第三人称单数", cefr: "A1" } },
      }),
    ]);
    const items = screen.getByTestId("plan-card-items");
    expect(items).toHaveTextContent("复习 8 个词");
    expect(items).toHaveTextContent("做一组语法练习：第三人称单数");
    expect(items).toHaveTextContent("预计 10 分钟");
    expect(screen.getByRole("button", { name: "撤销" })).toBeInTheDocument();
  });
});
