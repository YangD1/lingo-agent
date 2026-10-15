import { expect, type Page, test } from "@playwright/test";

import { answerPractice, register, uniqueEmail, useFakeModel } from "./helpers";

test.use({ locale: "zh-CN" });

const input = (page: Page) => page.getByRole("textbox", { name: /输入消息/ });
const replies = (page: Page) =>
  page.getByRole("list", { name: "消息" }).locator(':scope > li[data-role="assistant"]');

// The grammar course (ADR 0044): the first lesson, the tutor's opening, the pass quiz in
// the chat, and the next lesson once passed.
test("course: first lesson, pass quiz in the chat, then the next lesson", async ({ page }) => {
  await register(page, uniqueEmail());
  await useFakeModel(page);

  await page.getByRole("navigation", { name: "主导航" }).getByRole("link", { name: "课程" }).click();
  await expect(page).toHaveURL(/\/course$/);
  // No placement test: the course starts at A1, lesson 1.
  const current = page.getByTestId("course-current");
  await expect(current).toContainText("继续学习：第 1 课");
  await expect(page.getByTestId("course-level-A1")).toBeVisible();
  const second = page.getByTestId("course-lesson").nth(1);
  const secondKc = await second.getAttribute("data-kc");
  await current.getByRole("button", { name: "开始" }).click();

  // The lesson's conversation: its bar, and the tutor speaks first.
  await expect(page).toHaveURL(/\/chat\?c=/);
  const bar = page.getByTestId("lesson-bar");
  await expect(bar).toContainText("第 1 课");
  await expect(replies(page).first()).not.toHaveAttribute("data-status", "streaming", { timeout: 15_000 });
  await expect(replies(page)).toHaveCount(1);

  // Asked for, the tutor gives the pass quiz as a card in the chat.
  await input(page).fill("给我测验");
  await input(page).press("Enter");
  const card = page.getByTestId("quiz-card");
  await expect(card).toHaveAttribute("data-purpose", "quiz");
  await expect(card.getByTestId("practice-item")).toBeVisible({ timeout: 30_000 });

  // Every item answered with the fake model's key, one at a time.
  for (let n = 0; n < 10 && (await card.getByTestId("practice-item").isVisible()); n++) {
    await answerPractice(page, false);
    await expect(card.getByTestId("practice-verdict")).toHaveAttribute("data-correct", "true");
    await card.getByTestId("practice-next").click();
  }
  const summary = card.getByTestId("quiz-summary");
  await expect(summary).toHaveAttribute("data-passed", "true");
  await expect(summary).toContainText("测验结果 · 通过");
  await expect(summary).toContainText("答对 5 / 5");

  // Passed: the bar says so and leads to the next lesson.
  await expect(bar).toHaveAttribute("data-state", /passed|review/);
  const lessonChat = page.url();
  await bar.getByRole("button", { name: "下一课：第 2 课" }).click();
  await expect(page).not.toHaveURL(lessonChat);
  await expect(bar).toContainText("第 2 课");

  // Back on the course page: lesson 1 passed, lesson 2 open and current.
  await page.goto("/course");
  await expect(page.getByTestId("course-lesson").first()).toHaveAttribute("data-state", /passed|review/);
  await expect(page.locator(`[data-testid=course-lesson][data-kc="${secondKc}"]`)).toHaveAttribute(
    "data-state",
    "learning",
  );
  await expect(page.getByTestId("course-current")).toContainText("继续学习：第 2 课");
});

test("course: testing out of a locked lesson opens its quiz, without the tutor's lesson", async ({ page }) => {
  await register(page, uniqueEmail());
  await useFakeModel(page);

  // The first locked lesson, from the course itself; its level opened on the page.
  const course = await (await page.request.get("/api/course")).json();
  const locked = course.lessons.find((l: { state: string }) => l.state === "locked");
  expect(locked).toBeTruthy();
  await page.goto("/course");
  const level = page.getByTestId(`course-level-${locked.cefr}`);
  const header = level.getByRole("button", { name: new RegExp(locked.cefr) });
  if ((await header.getAttribute("aria-expanded")) !== "true") await header.click();
  const row = level.locator(`[data-testid=course-lesson][data-kc="${locked.kc_id}"]`);
  await expect(row).toHaveAttribute("data-state", "locked");
  await expect(row).toContainText("先过关：");
  await row.getByRole("button", { name: "我已经会了" }).click();

  // Straight to the quiz in the lesson's conversation: no model reply was asked for.
  await expect(page).toHaveURL(/\/chat\?c=/);
  await expect(page.getByTestId("lesson-bar")).toContainText(`第 ${locked.number} 课`);
  const card = page.getByTestId("quiz-card");
  await expect(card.getByTestId("practice-item")).toBeVisible({ timeout: 30_000 });
  await page.waitForTimeout(1_000); // time enough for an opening to have started
  await expect(replies(page)).toHaveCount(0);
});
