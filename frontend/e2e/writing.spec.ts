import { expect, type Page, test } from "@playwright/test";

import { register, uniqueEmail, useFakeModel } from "./helpers";

test.use({ locale: "zh-CN" });

// The fake model marks each "she like" and puts the quoted word on the word list
// (e2e/fake_llm.py); "ubiquitous" is in the sample dictionary.
const ESSAY = [
  "My sister is a nurse and she works at night.",
  "On weekends she like music and long walks in the park.",
  'Phones are "ubiquitous" in our city, so we often leave them at home on Sundays.',
].join(" ");

/** The review of one piece of writing, once it is done. */
async function expectReview(page: Page): Promise<void> {
  await expect(page.getByTestId("writing-summary")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId("writing-summary")).toContainText("1 处语法错误，已记入学习者模型");
  await expect(page.getByTestId("writing-summary")).toContainText(
    "A clear piece of writing; watch the verb endings.",
  );
  await expect(page.getByTestId("writing-score")).toHaveCount(4);
  await expect(page.getByTestId("writing-summary")).toContainText("已收进生词本：ubiquitous");

  // Only the sentence with a mistake is marked; its explanation opens on demand.
  await expect(page.getByTestId("writing-corrected")).toHaveCount(1);
  await expect(page.getByTestId("writing-corrected")).toContainText(
    "On weekends she likes music and long walks in the park.",
  );
  await expect(page.getByTestId("writing-explanation")).toHaveCount(0);
  await page.getByRole("button", { name: /错误：she like/ }).click();
  const explanation = page.getByTestId("writing-explanation");
  await expect(explanation).toContainText("she like → she likes");
  await expect(explanation).toContainText("Add -s to the verb after he, she or it.");
}

test("writing page: submit → reviewed sentence by sentence → history → delete", async ({ page }) => {
  await register(page, uniqueEmail());
  await useFakeModel(page);

  await page.getByRole("navigation", { name: "主导航" }).getByRole("link", { name: "写作" }).click();
  await expect(page).toHaveURL(/\/writing$/);
  await expect(page.getByText("还没有写作记录。")).toBeVisible();
  await expect(page.getByTestId("writing-submit")).toBeDisabled();

  await page.getByRole("button", { name: "不写题目" }).click();
  await page.getByTestId("writing-text").fill(ESSAY);
  await expect(page.getByTestId("writing-count")).toContainText("36 个英文单词");
  await page.getByTestId("writing-submit").click();

  await expect(page).toHaveURL(/\/writing\/\d+$/);
  await expect(page.getByRole("heading", { name: "没有题目" })).toBeVisible();
  await expectReview(page);

  // Listed on the writing page, and the draft was cleared.
  await page.getByRole("link", { name: "← 写作" }).click();
  await expect(page.getByTestId("writing-text")).toHaveValue("");
  const history = page.getByTestId("writing-history");
  await expect(history).toHaveCount(1);
  await expect(history).toContainText("1 处语法错误");
  await history.getByRole("link").click();
  await expect(page).toHaveURL(/\/writing\/\d+$/);

  // Deleting asks first, then goes back to an empty history.
  await page.getByTestId("writing-delete").click();
  await page.getByRole("alertdialog").getByRole("button", { name: "删除" }).click();
  await expect(page).toHaveURL(/\/writing$/);
  await expect(page.getByText("还没有写作记录。")).toBeVisible();
});

test("chat: a long piece of writing goes to the writing coach → card → the review", async ({ page }) => {
  await register(page, uniqueEmail());
  await useFakeModel(page);

  // Long enough to be classified (60 words), and it asks for a review.
  const message = `Please review my writing. ${ESSAY} ${ESSAY}`;
  const input = page.getByRole("textbox", { name: /输入消息/ });
  await input.fill(message);
  await input.press("Enter");

  const card = page.getByTestId("tutor-card");
  await expect(card).toContainText("作文批改", { timeout: 30_000 });
  await expect(page.getByRole("button", { name: /^私教做了什么：/ }).first()).toContainText(
    "写作教练",
  );
  await card.getByRole("link", { name: "查看逐句批改" }).click();

  await expect(page).toHaveURL(/\/writing\/\d+$/);
  await expect(page.getByTestId("writing-summary")).toBeVisible({ timeout: 30_000 });
  // The sentence with a mistake appears twice in the message: both are corrected.
  await expect(page.getByTestId("writing-corrected")).toHaveCount(2);
  await page.getByRole("link", { name: "来自和私教的对话（打开对话）" }).click();
  await expect(page).toHaveURL(/\/chat\?c=/);
  await expect(page.getByTestId("tutor-card")).toContainText("作文批改");
});
