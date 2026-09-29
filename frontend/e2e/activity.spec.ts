import { expect, type Page, test } from "@playwright/test";

import { register, uniqueEmail, useFakeModel } from "./helpers";

test.use({ locale: "zh-CN" });

// The fake model remembers what follows "remember that" and tags "she like" as a
// third-person -s mistake (e2e/fake_llm.py).
const input = (page: Page) => page.getByRole("textbox", { name: /输入消息/ });
const replies = (page: Page) =>
  page.getByRole("list", { name: "消息" }).locator(':scope > li[data-role="assistant"]');
const activityOf = (reply: ReturnType<Page["locator"]>) =>
  reply.getByRole("button", { name: /^私教做了什么：/ });

async function send(page: Page, text: string) {
  await input(page).fill(text);
  await input(page).press("Enter");
  await expect(page.getByRole("button", { name: "发送" })).toBeVisible();
}

test("each reply shows what the tutor did, and the learner can hide it", async ({ page }) => {
  await register(page, uniqueEmail());
  await useFakeModel(page);

  await send(page, "She like music, and please remember that I have a sister.");
  // Background results arrive by polling after the reply.
  const first = activityOf(replies(page).first());
  await expect(first).toHaveText("私教做了什么：记下 1 条 · 标记 1 个语法错误", {
    timeout: 15_000,
  });

  await first.click();
  const details = replies(page).first();
  await expect(details.getByText("I have a sister.", { exact: true })).toBeVisible();
  await expect(details.getByText("She like", { exact: true })).toBeVisible();
  await expect(details.getByText(/一般现在时第三人称单数 -s（A1）/)).toBeVisible();
  await expect(details.getByRole("link", { name: "管理记忆" })).toHaveAttribute("href", "/memory");

  // The next turn reads the fact the first one saved.
  await send(page, "Thanks!");
  await expect(activityOf(replies(page).nth(1))).toContainText("读取 1 条记忆");

  // Reopening the conversation shows it again, from the server.
  await page.reload();
  await expect(activityOf(replies(page).first())).toHaveText(
    "私教做了什么：记下 1 条 · 标记 1 个语法错误",
  );
  const conversationUrl = page.url();

  // Hidden: display only.
  await page.goto("/settings");
  const toggle = page.getByRole("checkbox", { name: /在私教回复下显示/ });
  await expect(toggle).toBeChecked();
  await toggle.uncheck();
  await page.goto(conversationUrl);
  await expect(replies(page)).toHaveCount(2);
  await expect(page.getByRole("button", { name: /^私教做了什么：/ })).toHaveCount(0);
  await page.goto("/memory");
  await expect(page.getByRole("list", { name: "私教记住的事" })).toContainText("I have a sister.");

  await page.goto("/settings");
  await page.getByRole("checkbox", { name: /在私教回复下显示/ }).check();
  await page.goto(conversationUrl);
  await expect(activityOf(replies(page).first())).toBeVisible();
});
