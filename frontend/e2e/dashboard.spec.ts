import { expect, type Page, test } from "@playwright/test";

import { PSEUDOWORDS, register, uniqueEmail, useFakeModel } from "./helpers";

test.use({ locale: "zh-CN" });

// The fake model tags "she like" as a third-person -s mistake (e2e/fake_llm.py).
const KC_NAME = "一般现在时第三人称单数 -s";

type Question = { id: string; stage: "vocab" | "grammar"; word?: string };
type Placement = { id: string; question: Question | null };

/** The whole placement test through the API; the page flow has its own spec. */
async function finishPlacement(page: Page): Promise<void> {
  const start = await page.request.post("/api/placement", { data: {} });
  expect(start.status()).toBe(200);
  let state = (await start.json()) as Placement;
  while (state.question) {
    const q = state.question;
    const answer =
      q.stage === "vocab" ? { yes: !PSEUDOWORDS.has(q.word ?? "") } : { choice: 0 };
    const response = await page.request.post(`/api/placement/${state.id}/answer`, {
      data: { question_id: q.id, ...answer },
    });
    expect(response.status()).toBe(200);
    state = (await response.json()) as Placement;
  }
}

/** Choose a book and learn its first two new words. */
async function reviewTwoWords(page: Page): Promise<void> {
  const book = await page.request.put("/api/vocab/book", {
    data: { book_id: "oxford3000", daily_new: null },
  });
  expect(book.status()).toBe(204);
  const queue = (await (await page.request.get("/api/vocab/queue")).json()) as {
    new: { word: { id: number } }[];
  };
  for (const item of queue.new.slice(0, 2)) {
    const rated = await page.request.post("/api/vocab/reviews", {
      data: { word_id: item.word.id, rating: 3 },
    });
    expect(rated.status()).toBe(200);
  }
}

test("dashboard: guides a new learner, then charts what they did", async ({ page }) => {
  await register(page, uniqueEmail());
  await page.getByRole("link", { name: "看板", exact: true }).click();
  await expect(page).toHaveURL(/\/dashboard$/);

  // New learner: guidance instead of empty charts.
  await expect(page.getByTestId("stat-level")).toContainText("未评估");
  await expect(page.getByTestId("dashboard-book")).toContainText("还没选词书");
  await expect(page.getByTestId("dashboard-grammar")).toContainText("还没有语法记录");
  await expect(page.getByTestId("dashboard-skills")).toContainText("还没有技能估计");
  await expect(page.getByTestId("dashboard-errors")).toContainText("没有记录到语法错误");
  await expect(page.getByTestId("activity-summary")).toContainText("还没有学习记录");
  await expect(page.locator(".recharts-surface")).toHaveCount(0);

  await finishPlacement(page);
  await reviewTwoWords(page);
  await useFakeModel(page);
  await page.getByRole("link", { name: "对话", exact: true }).click();
  // The dashboard has a message box of its own (today's conversation): wait for the chat page.
  await expect(page.getByRole("navigation", { name: "会话列表" })).toBeVisible();
  const input = page.getByRole("textbox", { name: /输入消息/ });
  await input.fill("She like music.");
  await input.press("Enter");
  await expect(
    page.getByRole("button", { name: /^私教做了什么：/ }).first(),
  ).toContainText("标记 1 个语法错误", { timeout: 15_000 });

  await page.getByRole("link", { name: "看板", exact: true }).click();
  await expect(page.getByTestId("stat-level")).toContainText(/[ABC][12]/);
  await expect(page.getByTestId("stat-vocab")).toContainText("约");
  await expect(page.getByTestId("stat-streak")).toContainText("1 天");
  await expect(page.getByTestId("stat-streak")).toContainText("今天已学习");

  const book = page.getByTestId("dashboard-book");
  await expect(book.locator(".recharts-pie")).toBeVisible();
  await expect(book.getByTestId("book-summary")).toContainText("学习中 2");
  await expect(page.getByTestId("dashboard-grammar").getByTestId("grammar-row")).toHaveCount(6);
  await expect(page.getByTestId("dashboard-skills").getByTestId("skill-bar")).toHaveCount(2);
  await expect(page.getByTestId("dashboard-skill-vocab")).toContainText("约");
  await expect(page.getByTestId("dashboard-skill-listening")).toContainText("未评估");

  const today = page.getByTestId("dashboard-activity").getByRole("listitem").last();
  await expect(today).toHaveAttribute("data-level", "4");
  await expect(today).toHaveAttribute("title", /复习 2 次，对话 1 轮/);

  // A common mistake leads to its grammar point.
  await page.getByTestId("dashboard-errors").getByRole("link", { name: new RegExp(KC_NAME) }).click();
  await expect(page).toHaveURL(/\/learner\?kc=g\.present_simple_third_person$/);
});
