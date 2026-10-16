import { expect, type Page, test } from "@playwright/test";

import { answerPractice, register, uniqueEmail, useFakeModel } from "./helpers";

test.use({ locale: "zh-CN" });

const input = (page: Page) => page.getByRole("textbox", { name: /输入消息/ });

// A quiz asked for in a free chat (ADR 0046): the context gives no grammar point id, so
// the tutor names the point and the questions come as a card, not in its reply.
test("asked for questions in a free chat, the tutor gives a quiz card", async ({ page }) => {
  await register(page, uniqueEmail());
  await useFakeModel(page);
  await page.goto("/chat");

  await input(page).fill("出点题给我测试吧");
  await input(page).press("Enter");
  const card = page.getByTestId("quiz-card");
  await expect(card).toHaveAttribute("data-purpose", "quiz");
  await expect(card.getByTestId("practice-item")).toBeVisible({ timeout: 30_000 });
  // The first item shows while the rest are still written (ADR 0048).
  await expect(card).toHaveAttribute("data-status", "generating");
  await expect(card.getByTestId("practice-progress")).toHaveText("第 1 / 5 题");

  for (let n = 1; n <= 5; n++) {
    // The next item may still be written: the card waits for it, then shows it.
    await expect(card.getByTestId("practice-progress")).toHaveText(`第 ${n} / 5 题`, { timeout: 10_000 });
    await answerPractice(page, false);
    await expect(card.getByTestId("practice-verdict")).toHaveAttribute("data-correct", "true");
    await card.getByTestId("practice-next").click();
  }
  const summary = card.getByTestId("quiz-summary");
  await expect(summary).toHaveAttribute("data-passed", "true");
  await expect(summary).toContainText("答对 5 / 5");
});
