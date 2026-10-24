import { expect, type Page, test } from "@playwright/test";

import { register, uniqueEmail, useFakeModel } from "./helpers";

// The tutor's follow-ups under a reply (ADR 0064): a "why" question fires the rule, and
// the fake chat_deep model writes FOLLOW_UP (e2e/fake_llm.py).
test.use({ locale: "zh-CN" });

const FOLLOW_UP = "It links a past action to the present.";

const input = (page: Page) => page.getByRole("textbox", { name: /输入消息/ });
const messages = (page: Page) =>
  page.getByRole("list", { name: "消息" }).locator(':scope > li > [data-slot="message"]');
const followUps = (page: Page) => messages(page).locator('[data-slot="follow-up"]');

async function send(page: Page, text: string) {
  await input(page).fill(text);
  await input(page).press("Enter");
}

test("a follow-up streams under the reply and is still there after a reload", async ({ page }) => {
  await register(page, uniqueEmail());
  await useFakeModel(page);

  const asked = "Why do we say I have eaten?";
  await send(page, asked);
  const reply = messages(page).nth(1);
  await expect(reply.locator('[data-slot="follow-up"]')).toHaveText(`补充${FOLLOW_UP}`);
  await expect(reply).toContainText(`Nice try! You said: ${asked}`);
  await expect(page.getByRole("button", { name: "发送" })).toBeVisible(); // the turn is over

  await page.reload();
  await expect(messages(page)).toHaveCount(2);
  await expect(followUps(page)).toHaveCount(1);
  // The reply's own text, then the heading, then the follow-up.
  await expect(messages(page).nth(1)).toHaveText(`Nice try! You said: ${asked}补充${FOLLOW_UP}`);
});

test("a follow-up that doesn't start in time is skipped and the chat goes on", async ({ page }) => {
  await register(page, uniqueEmail());
  await useFakeModel(page);
  // The shortest wait for a follow-up's first words; the fake takes 7 s here.
  const limits = await page.request.put("/api/tenant/deepen", {
    data: {
      enabled: true,
      max_segments: 1,
      first_chunk_seconds: 5,
      total_seconds: 60,
      max_tokens: 1500,
    },
  });
  expect(limits.ok()).toBe(true);

  await send(page, "Why is it have eaten? Take your time.");
  const followUp = followUps(page);
  await expect(followUp.getByRole("status")).toContainText("还在深入分析…");
  await expect(followUp).toContainText("补充分析没能及时开始，已跳过。", { timeout: 15_000 });
  await expect(followUp).not.toContainText(FOLLOW_UP);
  await expect(followUp.getByRole("status")).toHaveCount(0);

  await send(page, "Thanks");
  await expect(messages(page).nth(3)).toHaveText("Nice try! You said: Thanks");

  // Nothing of it was written, so nothing was saved (ADR 0064 §6).
  await page.reload();
  await expect(messages(page)).toHaveCount(4);
  await expect(followUps(page)).toHaveCount(0);
});

test("sending while a follow-up is written stops it and sends", async ({ page }) => {
  await register(page, uniqueEmail());
  await useFakeModel(page);

  const asked = "Why is it have eaten? Take your time.";
  await send(page, asked);
  await expect(followUps(page).getByRole("status")).toContainText("还在深入分析…");
  // Nothing typed: the button stops; with text, it sends over the follow-up.
  await expect(page.getByRole("button", { name: "停止" })).toBeVisible();
  await send(page, "Thanks");

  await expect(messages(page).nth(3)).toHaveText("Nice try! You said: Thanks");
  await expect(messages(page).nth(1)).toContainText(`Nice try! You said: ${asked}`);
  await expect(followUps(page)).toHaveText("补充补充分析已停止。");

  await page.reload();
  await expect(messages(page)).toHaveCount(4);
  await expect(messages(page).nth(1)).toContainText(`Nice try! You said: ${asked}`);
});
