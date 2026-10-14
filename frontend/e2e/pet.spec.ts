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
  // The first open of the day: the assistant speaks first (ADR 0041); then it's our turn.
  await expect(window.locator('li[data-role="assistant"]')).toContainText("of the last 7 days");
  await expect(window.locator('li[data-status="streaming"]')).toHaveCount(0);
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

test("the pet's window is resized by its free corner, and keeps the size", async ({ page }) => {
  await register(page, uniqueEmail("pet-resize"));
  await useFakeModel(page);
  await page.goto("/learner");

  await pet(page).getByTestId("tutor-pet-button").click();
  const window = page.getByTestId("pet-chat");
  await expect(window).toBeVisible();
  // 28rem wide, as tall as fits (720 − 2rem).
  const before = (await window.boundingBox())!;
  expect(Math.round(before.width)).toBe(448);
  expect(Math.round(before.height)).toBe(688);

  // The pet is on the right: the grip is the top-left corner. Smaller, down and to the right.
  // Held 8px in: the rounded corner clips its very tip.
  const grip = (await window.getByTestId("pet-chat-resize").boundingBox())!;
  await page.mouse.move(grip.x + 8, grip.y + 8);
  await page.mouse.down();
  await page.mouse.move(grip.x + 68, grip.y + 108, { steps: 5 });
  await page.mouse.up();
  const after = (await window.boundingBox())!;
  expect(Math.round(after.width)).toBe(388);
  expect(Math.round(after.height)).toBe(588);
  // The side by the pet and the bottom stayed put.
  expect(Math.round(after.x + after.width)).toBe(Math.round(before.x + before.width));
  expect(Math.round(after.y + after.height)).toBe(Math.round(before.y + before.height));
  await page.screenshot({ path: test.info().outputPath("pet-resized.png") });

  // Kept for next time; a double-click goes back to the default.
  await page.keyboard.press("Escape");
  await expect(window).toBeHidden();
  await pet(page).getByTestId("tutor-pet-button").click();
  await expect.poll(async () => Math.round((await window.boundingBox())!.width)).toBe(388);
  await window.getByTestId("pet-chat-resize").dblclick();
  await expect.poll(async () => Math.round((await window.boundingBox())!.width)).toBe(448);
});

test("the first open of the day: the pet wears its AI clip, the assistant looks back once (ADR 0041)", async ({
  page,
}) => {
  await register(page, uniqueEmail("pet-opening"));
  await useFakeModel(page);
  await page.goto("/learner");

  // Opening it now would call a model: the clip says so before the tap.
  const button = pet(page).getByTestId("tutor-pet-button");
  await expect(pet(page).locator("canvas[data-clip]")).toHaveCount(1);
  await expect(button).toHaveAttribute("title", /今天第一次打开：JOJO 会先用 AI 总结最近 7 天的学习/);
  await page.screenshot({ path: test.info().outputPath("pet-clip.png") });

  await button.click();
  const window = page.getByTestId("pet-chat");
  const tutorSaid = window.locator('li[data-role="assistant"]');
  await expect(tutorSaid).toHaveCount(1);
  await expect(tutorSaid).toContainText("You studied on 0 of the last 7 days.");
  await expect(window.getByRole("heading")).toContainText("今天的学习");
  // Begun: the clip comes off, and the name says nothing about AI any more.
  await expect(pet(page).locator("canvas[data-clip]")).toHaveCount(0);
  await expect(button).toHaveAttribute("title", "和 JOJO 聊天");
  await page.screenshot({ path: test.info().outputPath("pet-opening.png") });

  // Again today: the same conversation, no second opening.
  await page.keyboard.press("Escape");
  await button.click();
  await expect(tutorSaid).toHaveCount(1);
  await page.keyboard.press("Escape");

  // The dashboard's today is the same conversation.
  await page.goto("/dashboard");
  await expect(page.getByTestId("today").locator('li[data-role="assistant"]')).toContainText(
    "You studied on 0 of the last 7 days.",
  );
  await expect(pet(page).locator("canvas[data-clip]")).toHaveCount(0);

  // A new chat from the window, gone on with until the page is reloaded.
  await button.click();
  await window.getByRole("button", { name: "新对话" }).click();
  await expect(tutorSaid).toHaveCount(0);
  const input = window.getByRole("textbox", { name: /输入消息/ });
  await input.fill("hello there");
  await input.press("Enter");
  await expect(tutorSaid).toContainText("You said: hello there");
  await page.keyboard.press("Escape");
  await button.click();
  await expect(tutorSaid).toContainText("You said: hello there");
  await page.keyboard.press("Escape");
  await page.reload();
  await button.click();
  await expect(tutorSaid).toContainText("You studied on 0 of the last 7 days.");
});

test("with the daily opening switched off, the pet wears no clip and waits", async ({ page }) => {
  await register(page, uniqueEmail("pet-no-opening"));
  await useFakeModel(page);
  // Left out: the defaults (the pet on).
  expect((await page.request.put("/api/tutor", { data: { daily_opening: false } })).ok()).toBe(true);
  await page.goto("/learner");

  await expect(pet(page).getByTestId("tutor-pet-button")).toHaveAttribute("title", "和 JOJO 聊天");
  await expect(pet(page).locator("canvas[data-clip]")).toHaveCount(0);
  await pet(page).getByTestId("tutor-pet-button").click();
  const window = page.getByTestId("pet-chat");
  // The dashboard's greeting and quick replies, no model call.
  await expect(window.getByTestId("today-greeting")).toBeVisible();
  await expect(window.locator('li[data-role="assistant"]')).toHaveCount(0);
  expect(await (await page.request.get("/api/conversations")).json()).toEqual([]);
});
