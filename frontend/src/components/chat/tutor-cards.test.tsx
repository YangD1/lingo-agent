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
});
