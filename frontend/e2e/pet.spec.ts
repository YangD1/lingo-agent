import { expect, type Page, test } from "@playwright/test";

import { register, uniqueEmail, useFakeModel } from "./helpers";

test.use({ locale: "zh-CN" });

// The desk pet as a way in and a reminder (ADR 0039): a short command said in its window
// opens a bubble asking about it, then the thing itself; with no model set up it leads to
// the settings card for it, unasked.

const pet = (page: Page) => page.getByTestId("tutor-pet");
const bubble = (page: Page) => page.getByTestId("pet-bubble");

// The config starts every test with today's reminders used up (playwright.config.ts).
async function letThePetRemind(page: Page) {
  await page.evaluate(() => window.localStorage.removeItem("lingo.tutorPet.nudges"));
}

test("with no model, the pet leads to the settings card for one", async ({ page }) => {
  await register(page, uniqueEmail("pet-setup"));
  await letThePetRemind(page);
  await page.goto("/vocab");

  // Unasked, a few seconds after arriving.
  await expect(bubble(page)).toBeVisible({ timeout: 15_000 });
  await expect(bubble(page)).toHaveAttribute("data-key", "nudge:setup_model");
  await expect(bubble(page)).toContainText("还没有能用的对话模型");
  await page.screenshot({ path: test.info().outputPath("pet-nudge.png") });
  await bubble(page).getByRole("link", { name: "去设置" }).click();
  await expect(page).toHaveURL(/\/settings#connections$/);
  await expect(page.locator("#connections")).toHaveAttribute("data-flash", "");
  await expect(bubble(page)).toBeHidden();

  // Said today: not again on the next page.
  await page.goto("/learner");
  await page.waitForTimeout(6_000);
  await expect(bubble(page)).toBeHidden();

  // The window says so too, and still opens things.
  await pet(page).getByTestId("tutor-pet-button").click();
  const window = page.getByTestId("pet-chat");
  await expect(window.getByTestId("pet-chat-no-model")).toBeVisible();
  await expect(window.getByTestId("pet-chat-shortcuts").getByRole("link", { name: "阅读" })).toHaveAttribute(
    "href",
    "/reading",
  );
});

test("“我要背单词” in the pet's window asks, then opens flashcards in place", async ({ page }) => {
  await register(page, uniqueEmail("pet-command"));
  await useFakeModel(page);
  await page.goto("/learner");

  await pet(page).getByTestId("tutor-pet-button").click();
  const window = page.getByTestId("pet-chat");
  await expect(window).toBeVisible();
  await expect(window.getByTestId("pet-chat-no-model")).toHaveCount(0);
  const input = window.getByRole("textbox", { name: /输入消息/ });
  await input.fill("我要背单词");
  await input.press("Enter");

  // Not sent to the tutor: the window goes, the pet asks.
  await expect(window).toBeHidden();
  await expect(bubble(page)).toHaveAttribute("data-key", "ask:vocab_review");
  await expect(bubble(page)).toContainText("要开始背单词吗？");
  await page.screenshot({ path: test.info().outputPath("pet-ask.png") });
  await bubble(page).getByRole("link", { name: "开始" }).click();
  await expect(page).toHaveURL(/\/learner\?review=all$/);
  await expect(page.getByTestId("review-deck")).toBeVisible();
  await expect(bubble(page)).toBeHidden();
  await page.getByTestId("review-close").click();
  await expect(page.getByTestId("review-deck")).toHaveCount(0);

  // Nothing reached the tutor: no conversation has that message.
  const conversations = await (await page.request.get("/api/conversations")).json();
  for (const c of conversations as { id: string }[]) {
    const messages = await (await page.request.get(`/api/conversations/${c.id}/messages`)).json();
    expect(JSON.stringify(messages)).not.toContain("我要背单词");
  }

  // A question goes to the tutor as usual.
  await pet(page).getByTestId("tutor-pet-button").click();
  await input.fill("背单词有什么技巧");
  await input.press("Enter");
  await expect(window.locator('li[data-role="user"]').last()).toContainText("背单词有什么技巧");
  await expect(bubble(page)).toHaveCount(0);
});
