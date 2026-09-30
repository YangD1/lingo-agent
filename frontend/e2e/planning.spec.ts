import { expect, test } from "@playwright/test";

import { answerOne, register, uniqueEmail, useFakeModel } from "./helpers";

test.use({ locale: "zh-CN" });

test("planning: placement result → advice → the tutor proposes a word book → confirm → undo", async ({
  page,
}) => {
  await register(page, uniqueEmail());
  await useFakeModel(page);

  await page.goto("/placement");
  await page.getByRole("button", { name: "开始", exact: true }).click();
  while (!(await page.getByTestId("placement-result").isVisible())) await answerOne(page);
  const level = await page.getByTestId("placement-level").textContent();

  // The advice is rewritten for the new result right away, and shown under it.
  const next = page.getByTestId("placement-next");
  await expect(next.getByTestId("advice-item").first()).toBeVisible();
  await expect(next.getByTestId("advice-item").filter({ hasText: "趁热练一练" })).toHaveCount(0);
  await expect(next.getByTestId("ai-badge-plan_start")).toBeVisible();

  // The tutor opens the planning conversation with the result.
  await next.getByRole("link", { name: "和私教聊聊怎么学" }).click();
  await expect(page).toHaveURL(/\/chat\?c=/);
  const replies = page.locator("li[data-role=assistant]");
  await expect(replies.first()).toContainText(`Your level is ${level}. What is your goal?`);
  await expect(page.getByRole("button", { name: /学习规划/ }).first()).toBeVisible();

  // Asked about a word book, it proposes one on a card; nothing changes until confirmed.
  const input = page.getByRole("textbox", { name: /输入消息/ });
  await input.fill("帮我选一本词书");
  await input.press("Enter");
  const card = page.getByTestId("tutor-card");
  await expect(card).toContainText("把词书换成 牛津 3000 核心词");
  await expect(card).toContainText("每天 10 个新词");
  await expect(replies.nth(1)).toContainText("I've put a suggestion on a card.");
  await expect(page.getByRole("button", { name: /^私教做了什么：/ }).nth(1)).toContainText(
    "展示了 1 张卡片",
  );

  await card.getByRole("button", { name: "确认" }).click();
  await expect(card).toContainText("已完成。");
  await page.getByRole("link", { name: "背单词" }).click();
  await expect(page.getByTestId("book-oxford3000").getByText("当前")).toBeVisible();

  // Undo, back in the conversation: no book again.
  await page.goBack();
  await expect(card).toContainText("已完成。");
  // Back to the page opened with ?plan=1 doesn't start another planning conversation.
  await expect(page.getByRole("button", { name: /学习规划/ })).toHaveCount(1);
  await card.getByRole("button", { name: "撤销" }).click();
  await expect(card).toContainText("已撤销，恢复成原来的设置。");
  await page.getByRole("link", { name: "背单词" }).click();
  await expect(page.getByText(/还没有选词书/)).toBeVisible();
});
