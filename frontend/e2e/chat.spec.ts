import { expect, type Page, test } from "@playwright/test";

import { register, uniqueEmail, useFakeModel } from "./helpers";

test.use({ locale: "zh-CN" });

const input = (page: Page) => page.getByRole("textbox", { name: /输入消息/ });
const messages = (page: Page) => page.getByRole("list", { name: "消息" }).locator("li");
const conversations = (page: Page) => page.getByRole("list", { name: "会话列表" }).locator("li");

async function send(page: Page, text: string) {
  await input(page).fill(text);
  await input(page).press("Enter");
}

test("without a model, sending guides the user to settings and keeps the text", async ({ page }) => {
  await register(page, uniqueEmail());

  await send(page, "Hello there");

  await expect(page.getByRole("alert").filter({ hasText: "还没有配置聊天模型" })).toBeVisible();
  await expect(page.getByRole("link", { name: "去设置" })).toHaveAttribute("href", "/settings");
  await expect(input(page)).toHaveValue("Hello there");
  await expect(conversations(page)).toHaveCount(0); // the empty conversation was cleaned up
  await expect(messages(page)).toHaveCount(0);
});

test("streams a reply, keeps history, and stops a long reply", async ({ page }) => {
  await register(page, uniqueEmail());
  await useFakeModel(page);

  await send(page, "I goed home");
  await expect(messages(page).nth(1)).toHaveText("Nice try! You said: I goed home");
  await expect(page).toHaveURL(/\/chat\?c=[0-9a-f-]{36}$/);
  await expect(conversations(page)).toHaveText(["I goed home"]);

  await page.reload();
  await expect(messages(page)).toHaveText(["I goed home", "Nice try! You said: I goed home"]);

  await send(page, "tell me a long story");
  await expect(messages(page).nth(3)).toContainText("word3");
  await page.getByRole("button", { name: "停止" }).click();
  await expect(messages(page).nth(3)).toContainText("已停止");
  const partial = await messages(page).nth(3).textContent();
  expect(partial).not.toContain("word39");
  await expect(page.getByRole("button", { name: "发送" })).toBeVisible();

  // The backend saved the user's message but not the partial reply.
  await page.reload();
  await expect(messages(page)).toHaveCount(3);
  await expect(messages(page).nth(2)).toHaveText("tell me a long story");
});

test("switches between conversations and deletes one", async ({ page }) => {
  await register(page, uniqueEmail());
  await useFakeModel(page);

  await send(page, "first topic");
  await expect(messages(page).nth(1)).toContainText("first topic");
  await page.getByRole("button", { name: "新对话" }).click();
  await expect(page).toHaveURL(/\/chat$/);
  await expect(messages(page)).toHaveCount(0);
  await send(page, "second topic");
  await expect(messages(page).nth(1)).toContainText("second topic");
  await expect(conversations(page)).toHaveText(["second topic", "first topic"]);

  await conversations(page).filter({ hasText: "first topic" }).getByRole("button").first().click();
  await expect(messages(page).first()).toHaveText("first topic");
  await page.goBack();
  await expect(messages(page).first()).toHaveText("second topic");

  page.once("dialog", (dialog) => dialog.accept());
  await conversations(page)
    .filter({ hasText: "second topic" })
    .getByRole("button", { name: "删除会话" })
    .click();
  await expect(conversations(page)).toHaveText(["first topic"]);
  await expect(page).toHaveURL(/\/chat$/);
});
