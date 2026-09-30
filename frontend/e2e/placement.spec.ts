import { readFileSync } from "node:fs";
import path from "node:path";

import { expect, type Page, test } from "@playwright/test";

import { register, uniqueEmail } from "./helpers";

test.use({ locale: "zh-CN" });

// Answering "no" to exactly the made-up words keeps the vocabulary result reliable and
// high, so the sample book's words are offered for marking known.
const PSEUDOWORDS = new Set(
  readFileSync(
    path.join(__dirname, "../../backend/app/adaptive/placement/pseudowords.txt"),
    "utf8",
  )
    .split("\n")
    .filter((line) => line && !line.startsWith("#")),
);

const progress = (page: Page) => page.getByTestId("placement-progress");

/** Answer the current question and wait for the next one (or the result). */
async function answerOne(page: Page): Promise<void> {
  const before = await progress(page).textContent();
  if (before?.includes("词汇")) {
    const word = await page.locator("[data-testid=placement-question] p[lang=en]").textContent();
    await page.keyboard.press(PSEUDOWORDS.has(word ?? "") ? "n" : "y");
  } else {
    await page.keyboard.press("1");
  }
  await expect(async () => {
    const done = await page.getByTestId("placement-result").isVisible();
    expect(done || (await progress(page).textContent()) !== before).toBe(true);
  }).toPass();
}

test("placement: banner, leave and come back, result, mark words known, learner page", async ({
  page,
}) => {
  await register(page, uniqueEmail());
  const banner = page.getByTestId("placement-banner");
  await expect(banner).toContainText("先做个入学测吧");
  await banner.getByRole("link", { name: "开始入学测" }).click();
  await expect(page).toHaveURL(/\/placement$/);

  await page.getByRole("button", { name: "开始", exact: true }).click();
  await expect(progress(page)).toHaveText("第一部分 · 词汇 · 第 1 / 40 题");
  await answerOne(page);
  await answerOne(page);

  // Leaving halfway: the chat banner says "continue", and the same question comes back.
  const word = await page.locator("[data-testid=placement-question] p[lang=en]").textContent();
  await page.getByRole("link", { name: "对话", exact: true }).click();
  await banner.getByRole("link", { name: "继续" }).click();
  await expect(progress(page)).toHaveText("第一部分 · 词汇 · 第 3 / 40 题");
  await expect(page.locator("[data-testid=placement-question] p[lang=en]")).toHaveText(word!);

  // The sample word list runs out early; then 20 grammar questions.
  while (!(await page.getByTestId("placement-result").isVisible())) await answerOne(page);
  await expect(page.getByTestId("placement-level")).toHaveText(/^(A1|A2|B1|B2|C1|C2)$/);
  await expect(page.getByTestId("placement-vocab-size")).toHaveText(/^约 [\d,]+ 词$/);
  await expect(page.getByTestId("placement-unreliable")).toHaveCount(0);

  // No book yet: nothing to mark, with a way to choose one.
  const known = page.getByTestId("placement-known");
  await known.getByRole("link", { name: "去选词书" }).click();
  await page.getByTestId("book-oxford3000").getByRole("button", { name: "学这本" }).click();
  await page.getByRole("link", { name: "入学测", exact: true }).click();
  await known.getByRole("button", { name: /^把这 \d+ 个词标为已认识$/ }).click();
  await expect(page.getByTestId("placement-known-marked")).toHaveText(/^已按入学测标熟 \d+ 个词。$/);
  await known.getByRole("button", { name: "撤销" }).click();
  await expect(known.getByRole("button", { name: /标为已认识/ })).toBeVisible();

  // The learner page reads the result; the chat page stops inviting.
  await page.getByRole("link", { name: "学习者模型" }).click();
  await expect(page.getByTestId("skill-vocab")).toHaveText(/^词汇：约 [\d,]+ 词/);
  await expect(page.getByTestId("skill-grammar")).toHaveText(/^语法：(A1|A2|B1|B2|C1|C2)（\d+ 次作答）$/);
  const first = page.getByRole("list", { name: "语法掌握度" }).getByRole("listitem").first();
  await first.getByRole("button").first().click();
  await expect(first.getByRole("link", { name: "来自入学测" }).first()).toBeVisible();

  await page.getByRole("link", { name: "对话", exact: true }).click();
  await expect(page.getByRole("button", { name: "发送" })).toBeVisible();
  await expect(banner).toHaveCount(0);

  // Retesting needs a second click.
  await page.getByRole("link", { name: "入学测", exact: true }).click();
  await page.getByRole("button", { name: "重新测试" }).click();
  await page.getByRole("button", { name: "确定重新测试" }).click();
  await expect(progress(page)).toHaveText("第一部分 · 词汇 · 第 1 / 40 题");
});
