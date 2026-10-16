import { expect, type Page, test } from "@playwright/test";

import { answerPractice, register, uniqueEmail, useFakeModel } from "./helpers";

test.use({ locale: "zh-CN" });

const input = (page: Page) => page.getByRole("textbox", { name: /输入消息/ });

/** Sends and waits for the reply to finish, so the next message can go. */
async function send(page: Page, text: string) {
  await input(page).fill(text);
  await input(page).press("Enter");
  await expect(page.getByRole("button", { name: "发送" })).toBeVisible();
}

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

// The tutor takes a card back in the same turn (ADR 0049): the card folds into its
// reason, and its questions stop being written.
test("the tutor withdraws a quiz card it gave, and its questions never come", async ({ page }) => {
  await register(page, uniqueEmail());
  await useFakeModel(page);
  await page.goto("/chat");

  await input(page).fill("出点题给我测试吧，算了又不想做了");
  await input(page).press("Enter");
  const card = page.getByTestId("tutor-card").filter({ has: page.getByText("私教撤回了这张卡") });
  await expect(card).toHaveAttribute("data-status", "withdrawn");
  await expect(card).toContainText("你改主意了");
  await expect(page.getByTestId("quiz-card")).toHaveCount(0);
  await expect(page.getByText("撤回了 1 张卡片")).toBeVisible();

  await card.getByRole("button", { name: "看原内容" }).click();
  await expect(card.getByTestId("withdrawn-original")).toContainText("通过测验");
  // Still taken back after a reload, and no questions turned up meanwhile.
  await page.reload();
  await expect(page.getByTestId("tutor-card")).toHaveAttribute("data-status", "withdrawn");
  // The reason comes with the card list too, not only with the streamed card.
  await expect(page.getByTestId("tutor-card")).toContainText("你改主意了");
  await expect(page.getByTestId("practice-item")).toHaveCount(0);
});

// Asked again (task 94): no daily cap, the unfinished quiz comes back where it stopped;
// asked for a new set, new questions are written.
test("asked again, the unfinished quiz comes back; a new set when asked for one", async ({ page }) => {
  await register(page, uniqueEmail());
  await useFakeModel(page);
  await page.goto("/chat");

  await send(page, "出点题给我测试吧");
  const first = page.getByTestId("quiz-card").nth(0);
  for (let n = 1; n <= 2; n++) {
    await expect(first.getByTestId("practice-progress")).toHaveText(`第 ${n} / 5 题`, { timeout: 30_000 });
    await answerPractice(page, false);
    await expect(first.getByTestId("practice-verdict")).toBeVisible();
    await first.getByTestId("practice-next").click();
  }

  await send(page, "再出点题吧");
  const again = page.getByTestId("quiz-card").nth(1);
  await expect(again.getByTestId("practice-progress")).toHaveText("第 3 / 5 题", { timeout: 30_000 });

  await send(page, "换一组，出点题");
  const fresh = page.getByTestId("quiz-card").nth(2);
  await expect(fresh.getByTestId("practice-progress")).toHaveText("第 1 / 5 题", { timeout: 30_000 });
  await expect(page.getByTestId("quiz-failed")).toHaveCount(0);
});
