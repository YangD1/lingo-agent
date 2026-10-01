import { expect, test } from "@playwright/test";

import { answerOne, register, uniqueEmail, useFakeModel } from "./helpers";

test.use({ locale: "zh-CN" });

// The planning conversation sits in the placement result (ADR 0016 §4). The fake model
// opens with the placement level and proposes a word book when asked (e2e/fake_llm.py).
test("planning: placement result → the tutor opens in the page → proposes a word book → confirm → undo", async ({
  page,
}) => {
  await register(page, uniqueEmail());
  await useFakeModel(page);

  await page.goto("/placement");
  await page.getByRole("button", { name: "开始", exact: true }).click();
  while (!(await page.getByTestId("placement-result").isVisible())) await answerOne(page);
  const level = await page.getByTestId("placement-level").textContent();

  // Nothing is created, and no model called, until the learner asks.
  const next = page.getByTestId("placement-next");
  await expect(next.getByTestId("ai-badge-plan_start")).toBeVisible();
  await expect(next.getByRole("link", { name: "在对话页继续" })).toHaveCount(0);
  expect(await (await page.request.get("/api/conversations")).json()).toEqual([]);

  // The tutor opens the planning conversation with the result, right here.
  await next.getByRole("button", { name: "和私教聊聊这次结果" }).click();
  const replies = next.locator("li[data-role=assistant]");
  await expect(replies.first()).toContainText(`Your level is ${level}. What is your goal?`);
  await expect(page).toHaveURL(/\/placement$/);

  // Asked about a word book, it proposes one on a card; nothing changes until confirmed.
  const input = next.getByRole("textbox", { name: /输入消息/ });
  await input.fill("帮我选一本词书");
  await input.press("Enter");
  const card = next.getByTestId("tutor-card");
  await expect(card).toContainText("把词书换成 牛津 3000 核心词");
  await expect(card).toContainText("每天 10 个新词");
  await expect(replies.nth(1)).toContainText("I've put a suggestion on a card.");
  await expect(next.getByRole("button", { name: /^私教做了什么：/ }).nth(1)).toContainText(
    "展示了 1 张卡片",
  );

  await card.getByRole("button", { name: "确认" }).click();
  await expect(card).toContainText("已完成。");
  await page.getByRole("link", { name: "背单词" }).click();
  await expect(page.getByTestId("book-oxford3000").getByText("当前")).toBeVisible();

  // Back on the result, the same conversation; undo there: no book again.
  await page.goto("/placement");
  await expect(card).toContainText("已完成。");
  await expect(replies).toHaveCount(2);
  await card.getByRole("button", { name: "撤销" }).click();
  await expect(card).toContainText("已撤销，恢复成原来的设置。");
  await page.getByRole("link", { name: "背单词" }).click();
  await expect(page.getByText(/还没有选词书/)).toBeVisible();

  // It is one conversation in the chat list, and continues there.
  await page.goto("/placement");
  await next.getByRole("link", { name: "在对话页继续" }).click();
  await expect(page).toHaveURL(/\/chat\?c=[0-9a-f-]{36}$/);
  await expect(page.getByRole("button", { name: /学习规划/ })).toHaveCount(1);
});
