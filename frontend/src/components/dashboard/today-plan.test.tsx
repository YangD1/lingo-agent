import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import type { Plan } from "@/lib/plan";

import zh from "../../../messages/zh-CN.json";
import { TodayPlan } from "./today-plan";

const api = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  api,
}));

const KC = { id: "g.past_simple", name_en: "Past simple", name_zh: "一般过去时" };

const PLAN: Plan = {
  id: "p1",
  day: "2026-10-09",
  status: "proposed",
  card_id: null,
  choice: { review: 20, new_words: 5, practice: true, reading: false, writing: false, speaking: false },
  items: [
    { kind: "review", minutes: 5, count: 20, done: 0, target: 20, complete: false, kc: null, article: null },
    { kind: "practice", minutes: 8, count: null, done: 0, target: 1, complete: false, kc: KC, article: null },
    { kind: "new_words", minutes: 5, count: 5, done: 0, target: 5, complete: false, kc: null, article: null },
  ],
  minutes: 18,
  budget: 20,
  budget_set: true,
  limits: { reviews_due: 22, new_left: 5, practice: true, reading: false, max_count: 500, speaking_minutes: 5 },
  estimates: { review: 0.25, new_words: 1, practice: 8, reading: 10, writing: 15, speaking: 10 },
};

function show(plan: Plan | null, error: string | null = null) {
  const onChange = vi.fn();
  const onReload = vi.fn();
  render(
    <NextIntlClientProvider locale="zh-CN" messages={zh}>
      <TodayPlan plan={plan} error={error} onChange={onChange} onReload={onReload} />
    </NextIntlClientProvider>,
  );
  return { onChange, onReload };
}

beforeEach(() => api.mockReset());

describe("TodayPlan", () => {
  it("lets the learner adjust the draft within today's limits, then confirm", async () => {
    const { onChange } = show(PLAN);
    expect(screen.getByText("按你每天 20 分钟排的，可以先调整再确认。")).toBeInTheDocument();
    expect(screen.getByTestId("plan-total")).toHaveTextContent("预计 18 分钟");

    const review = screen.getByTestId("plan-row-review");
    expect(review).toHaveTextContent("今天最多 22");
    // 20 -> 22 (capped at the due count), and the + turns off there.
    await userEvent.click(within(review).getByRole("button", { name: "复习 20 个词：增加" }));
    expect(review).toHaveTextContent("复习 22 个词");
    expect(within(review).getByRole("button", { name: /增加/ })).toBeDisabled();
    // Reading has nothing to read: its switch is off and disabled.
    const reading = screen.getByTestId("plan-row-reading");
    expect(reading).toHaveTextContent("订阅里没有没读过的文章");
    expect(within(reading).getByRole("switch")).toHaveAttribute("aria-disabled", "true");
    await userEvent.click(within(screen.getByTestId("plan-row-writing")).getByRole("switch"));
    expect(screen.getByTestId("plan-total")).toHaveTextContent("预计 34 分钟");
    // Speaking is never drafted; the learner adds it, done after 5 minutes of speaking.
    const speaking = screen.getByTestId("plan-row-speaking");
    expect(speaking).toHaveTextContent("今天自己说满 5 分钟就算完成");
    await userEvent.click(within(speaking).getByRole("switch"));
    expect(screen.getByTestId("plan-total")).toHaveTextContent("预计 44 分钟");

    const confirmed = { ...PLAN, status: "applied" as const };
    api.mockResolvedValueOnce(confirmed);
    await userEvent.click(screen.getByRole("button", { name: "确认计划" }));
    expect(api).toHaveBeenCalledWith("/plan/p1/confirm", {
      method: "POST",
      json: {
        tz: expect.any(String),
        choice: { review: 22, new_words: 5, practice: true, reading: false, writing: true, speaking: true },
      },
    });
    expect(onChange).toHaveBeenCalledWith(confirmed);
  });

  it("ticks off what is done and links to the rest", () => {
    show({
      ...PLAN,
      status: "applied",
      items: [
        { ...PLAN.items[0], done: 25, complete: true },
        PLAN.items[1],
        { ...PLAN.items[2], done: 2 },
        { kind: "speaking", minutes: 10, count: 5, done: 3, target: 5, complete: false, kc: null, article: null },
      ],
    });
    expect(screen.getByText("完成 1/4")).toBeInTheDocument();
    const review = screen.getByTestId("plan-item-review");
    expect(review).toHaveAttribute("data-complete", "true");
    // Never more than the target, and nothing to go to once done.
    expect(within(review).getByTestId("plan-progress")).toHaveTextContent("20/20");
    expect(within(review).queryByRole("link")).not.toBeInTheDocument();
    const practice = screen.getByTestId("plan-item-practice");
    expect(practice).toHaveTextContent("做一组语法练习：一般过去时");
    expect(within(practice).getByRole("link", { name: "去练习" })).toHaveAttribute(
      "href",
      "/practice?from=plan&kc=g.past_simple",
    );
    expect(within(screen.getByTestId("plan-item-new_words")).getByTestId("plan-progress")).toHaveTextContent(
      "2/5",
    );
    const speaking = screen.getByTestId("plan-item-speaking");
    expect(speaking).toHaveTextContent("一次口语练习");
    expect(within(speaking).getByTestId("plan-progress")).toHaveTextContent("3/5 分钟");
    expect(within(speaking).getByRole("link", { name: "去说" })).toHaveAttribute("href", "/speaking");
  });

  it("undoes a plan from the tutor's card on that card", async () => {
    const { onReload } = show({ ...PLAN, status: "applied", card_id: "k9" });
    expect(screen.getByText(/私教按你说的改过/)).toBeInTheDocument();
    api.mockResolvedValueOnce({});
    await userEvent.click(screen.getByRole("button", { name: "撤销" }));
    expect(api).toHaveBeenCalledWith("/cards/k9/undo", { method: "POST" });
    expect(onReload).toHaveBeenCalled();
  });

  it("says why a decision failed", async () => {
    show(PLAN);
    api.mockRejectedValueOnce(new ApiError(409, "plan_expired", "another day"));
    await userEvent.click(screen.getByRole("button", { name: "今天不要计划" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("这是之前某一天的计划");
  });

  it("is one line when declined, and tells a learner without daily minutes where to set them", () => {
    show({ ...PLAN, status: "declined" });
    expect(screen.getByTestId("plan-declined")).toHaveTextContent("今天不排计划");
    expect(screen.queryByTestId("plan-editor")).not.toBeInTheDocument();
  });

  it("assumes a default when daily minutes are not set", () => {
    show({ ...PLAN, budget_set: false });
    expect(screen.getByRole("link", { name: "记忆页" })).toHaveAttribute("href", "/memory");
  });

  it("shows nothing to plan without anything open", () => {
    show({
      ...PLAN,
      choice: { review: 0, new_words: 0, practice: false, reading: false, writing: false, speaking: false },
      items: [],
      limits: { ...PLAN.limits, reviews_due: 0, new_left: 0, practice: false },
    });
    expect(screen.getByText(/今天没有要做的/)).toBeInTheDocument();
  });
});
