import { expect, test } from "@playwright/test";

import { register, uniqueEmail } from "./helpers";

test.use({ locale: "zh-CN" });

// run_backend.py imports backend/tests/fixtures/ecdict_sample.csv. Its Oxford 3000 words
// by frequency: the, go, us, run, abandon, hello, colour (unranked, last).
const OXFORD = "oxford3000";

test("choose a book, screen known words, review, and see the progress", async ({ page }) => {
  await register(page, uniqueEmail());
  await page.getByRole("link", { name: "背单词" }).click();
  await expect(page).toHaveURL(/\/vocab$/);
  await expect(page.getByText(/还没有选词书/)).toBeVisible();

  const book = page.getByTestId(`book-${OXFORD}`);
  await book.getByRole("button", { name: "学这本" }).click();
  await expect(book.getByText("当前")).toBeVisible();
  await expect(page.getByTestId("today-counts")).toHaveText(
    "待复习 0 个 · 新词还剩 7 个（今天已开始 0 / 15）",
  );

  await page.getByRole("link", { name: "熟词筛选" }).click();
  await page.getByRole("button", { name: "the", exact: true }).click();
  await page.getByRole("button", { name: "go", exact: true }).click();
  await expect(page.getByTestId("screen-count")).toHaveText("已标记认识 2 / 7");
  await page.getByRole("button", { name: "好了，提交" }).click();
  await expect(page.getByTestId("screen-result")).toHaveText("这批 7 个词里你认识 2 个。");
  await page.getByRole("button", { name: "下一批" }).click();
  await expect(page.getByText("这本书的词你都看过了。")).toBeVisible();
  await page.getByRole("link", { name: "回到背单词" }).click();

  await expect(page.getByText(/建议先做熟词筛选/)).toHaveCount(0);
  await page.getByRole("link", { name: "开始" }).click();
  // Known words are skipped; the rest come most frequent first. Easy graduates a new
  // card for days, so none comes back today.
  for (const word of ["us", "run", "abandon", "hello", "colour"]) {
    await expect(page.getByRole("heading", { name: word, exact: true })).toBeVisible();
    await page.keyboard.press("Space");
    await expect(page.getByTestId("review-back")).toBeVisible();
    await page.keyboard.press("4");
  }
  const done = page.getByTestId("review-done");
  await expect(done).toContainText("复习了 5 张");

  await done.getByRole("link", { name: "回到背单词" }).click();
  await expect(page.getByTestId("today-counts")).toHaveText(
    "待复习 0 个 · 新词还剩 0 个（今天已开始 5 / 15）",
  );
  await expect(book).toContainText("学习中 5 · 已认识 2 · 已接触 100%");
  await page.reload();
  await expect(book.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "100");
});

test("add a word to my list by an inflected form, then remove it", async ({ page }) => {
  page.on("dialog", (dialog) => void dialog.accept());
  await register(page, uniqueEmail());
  await page.goto("/vocab/mine");
  await expect(page.getByText("还没有生词。")).toBeVisible();

  const input = page.getByRole("combobox", { name: "添加单词" });
  await input.fill("went");
  await input.press("Enter");
  await expect(page.getByRole("status")).toHaveText("已加入“go”（“went”的原形）。");
  const row = page.getByTestId("mine-go");
  await expect(row).toContainText("手动添加 · 未开始");

  await input.fill("wented");
  await input.press("Enter");
  // Next's route announcer is an alert too.
  await expect(page.getByRole("alert").filter({ hasText: /\S/ })).toHaveText("词库里没有这个词。");

  // Own words are learned without a book.
  await page.goto("/vocab/review");
  await expect(page.getByRole("heading", { name: "go", exact: true })).toBeVisible();
  await expect(page.getByText("生词本", { exact: true })).toBeVisible();

  await page.goto("/vocab/mine");
  await row.getByRole("button", { name: "删除" }).click();
  await expect(page.getByText("还没有生词。")).toBeVisible();
});
