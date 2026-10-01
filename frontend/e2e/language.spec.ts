import { expect, type Page, test } from "@playwright/test";

import { register, uniqueEmail, useFakeModel } from "./helpers";

test.use({ locale: "zh-CN" });

// ADR 0017: how much Chinese the tutor uses, looking words up in its replies, and
// translating a reply. The fake model (fake_llm.py) answers "which language" with the
// language the system prompt asks for, and marks translations with "译文 " / "(English) ".

const replies = (page: Page) =>
  page.getByRole("list", { name: "消息" }).locator(':scope > li[data-role="assistant"]');

async function chat(page: Page, text: string) {
  const input = page.getByRole("textbox", { name: /输入消息/ });
  await input.fill(text);
  await input.press("Enter");
  await expect(page.getByRole("button", { name: "发送" })).toBeVisible();
}

async function openChat(page: Page) {
  await register(page, uniqueEmail());
  await useFakeModel(page);
  await page.goto("/chat");
  await expect(page).toHaveURL(/\/chat$/);
  await expect(page.getByTestId("chat-language")).toBeVisible();
}

test("switch the tutor between mostly Chinese and mostly English", async ({ page }) => {
  await openChat(page);
  // No level yet: mostly Chinese, chosen by level.
  const mix = page.getByTestId("chat-language");
  await expect(mix.getByRole("radio", { name: "多说中文" })).toHaveAttribute("aria-checked", "true");
  await expect(page.getByText("按你的等级选的", { exact: false })).toBeVisible();

  await chat(page, "Which language?");
  await expect(replies(page).last().locator('[data-slot="message"]')).toHaveText("我们主要用中文聊。");

  // From the next reply on.
  await mix.getByRole("radio", { name: "多说英文" }).click();
  await expect(mix.getByRole("radio", { name: "多说英文" })).toHaveAttribute("aria-checked", "true");
  await chat(page, "Which language now?");
  await expect(replies(page).last().locator('[data-slot="message"]')).toHaveText(
    "We mainly talk in English.",
  );
  await expect(replies(page).first().locator('[data-slot="message"]')).toHaveText("我们主要用中文聊。");

  // It's the learner's setting: still there after a reload.
  await page.reload();
  await expect(
    page.getByTestId("chat-language").getByRole("radio", { name: "多说英文" }),
  ).toHaveAttribute("aria-checked", "true");
});

test("translate a reply and switch back", async ({ page }) => {
  await openChat(page);
  await chat(page, "I like apples.");
  const reply = replies(page).last();
  const bubble = reply.locator('[data-slot="message"]');
  await expect(bubble).toHaveText("Nice try! You said: I like apples.");

  const translate = reply.getByTestId("reply-translate");
  await expect(translate).toHaveText("看中文");
  await expect(reply.getByTestId("ai-badge-message_translate")).toBeVisible();
  await translate.click();
  await expect(bubble).toHaveText("译文 Nice try! You said: I like apples.");
  await expect(translate).toHaveText("看原文");
  // Translated once: switching back and forth calls nothing, so no AI badge.
  await expect(reply.getByTestId("ai-badge-message_translate")).toHaveCount(0);

  await translate.click();
  await expect(bubble).toHaveText("Nice try! You said: I like apples.");

  // Stored: after a reload, the translation comes back without the model.
  await page.reload();
  await replies(page).last().getByTestId("reply-translate").click();
  await expect(replies(page).last().locator('[data-slot="message"]')).toHaveText(
    "译文 Nice try! You said: I like apples.",
  );
});

test("AI example sentences for a word in a reply", async ({ page }) => {
  await openChat(page);
  await chat(page, "I had to abandon the plan.");

  await replies(page).last().locator('[data-word="abandon"]').click();
  const popup = page.getByTestId("word-popup");
  await expect(popup.getByTestId("ai-badge-word_examples")).toBeVisible();
  await popup.getByRole("button", { name: "AI 例句" }).click();
  await expect(popup.getByTestId("word-examples")).toContainText("I abandon every day.");
  await expect(popup.getByTestId("word-examples")).toContainText("我每天都 abandon。");
});
