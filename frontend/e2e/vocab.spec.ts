import { expect, type Page, test } from "@playwright/test";

import { register, uniqueEmail, useFakeModel } from "./helpers";

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

test("the back of a card shows real example sentences, and AI ones when asked", async ({
  page,
}) => {
  await register(page, uniqueEmail());
  await useFakeModel(page);
  await page.goto("/vocab");
  await page.getByTestId(`book-${OXFORD}`).getByRole("button", { name: "学这本" }).click();
  await page.getByRole("link", { name: "开始" }).click();

  // "the" comes first and has no sentence in run_backend.py's Tatoeba sample: only the button.
  await expect(page.getByRole("heading", { name: "the", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "显示答案" }).click();
  const examples = page.getByTestId("review-examples");
  await expect(examples.getByRole("listitem")).toHaveCount(0);
  await expect(examples.getByTestId("ai-badge-word_examples")).toBeVisible();
  await page.keyboard.press("4");

  await expect(page.getByRole("heading", { name: "go", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "显示答案" }).click();
  await expect(examples.getByRole("listitem")).toHaveCount(2);
  // Fewer uncommon words first. The word is bold, inflected forms too; the traditional
  // translation was simplified on import.
  await expect(examples.locator("strong")).toHaveText(["go", "went"]);
  await expect(examples).toContainText("我们现在一起回家吧。");
  const links = examples.getByRole("link", { name: "在 Tatoeba 查看这句" });
  await expect(links.first()).toHaveAttribute("href", "https://tatoeba.org/sentences/show/2");
  await expect(links.last()).toHaveAttribute("href", "https://tatoeba.org/sentences/show/1");
  await expect(examples).toContainText("来源：Tatoeba");

  await examples.getByRole("button", { name: "AI 例句" }).click();
  const ai = page.getByTestId("review-ai-examples");
  await expect(ai).toContainText("I go every day.");
  await expect(ai).toContainText("我每天都 go。");
  await expect(examples).toContainText("AI 生成");
  await expect(examples.getByRole("button", { name: "AI 例句" })).toHaveCount(0);
});

test("add a word to my list by an inflected form, then remove it", async ({ page }) => {
  await register(page, uniqueEmail());
  await page.goto("/vocab/mine");
  await expect(page.getByText("生词本还是空的")).toBeVisible();

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
  await row.getByRole("group").getByRole("button", { name: "删除" }).click();
  await expect(page.getByText("生词本还是空的")).toBeVisible();
});

const replies = (page: Page) =>
  page.getByRole("list", { name: "消息" }).locator(':scope > li[data-role="assistant"]');

async function chat(page: Page, text: string) {
  const input = page.getByRole("textbox", { name: /输入消息/ });
  await input.fill(text);
  await input.press("Enter");
  await expect(page.getByRole("button", { name: "发送" })).toBeVisible();
}

test("words asked about in chat are collected, and can be taken off again", async ({ page }) => {
  await register(page, uniqueEmail());
  await useFakeModel(page);

  // The fake model's reflection collects the word in 'what does "X" mean'.
  await chat(page, 'What does "went" mean?');
  const reply = replies(page).first();
  const line = reply.getByRole("button", { name: /^私教做了什么：/ });
  await expect(line).toContainText("收进生词本 1 个词", { timeout: 15_000 });
  await line.click();
  await expect(reply.getByRole("link", { name: "查看生词本" })).toHaveAttribute(
    "href",
    "/vocab/mine",
  );

  await page.goto("/vocab/mine");
  await expect(page.getByTestId("mine-go")).toContainText("对话中收集 · 未开始");

  await page.goBack();
  await replies(page).first().getByRole("button", { name: /^私教做了什么：/ }).click();
  await replies(page).first().getByRole("button", { name: "把 go 移出生词本" }).click();
  await expect(replies(page).first().getByText("已移出")).toBeVisible();
  await page.goto("/vocab/mine");
  await expect(page.getByText("生词本还是空的")).toBeVisible();
});

test("hover a word in a reply to look it up and add it to my list", async ({ page }) => {
  await register(page, uniqueEmail());
  await useFakeModel(page);
  await chat(page, "I had to abandon the plan.");

  // The fake tutor echoes the message back; its English words open the word popup.
  await replies(page).last().locator('[data-word="abandon"]').hover();
  const popup = page.getByTestId("word-popup");
  await expect(popup).toBeVisible();
  await expect(popup.getByTestId("word-sentence")).toContainText("abandon the plan");
  await popup.getByRole("button", { name: "加入生词本" }).click();
  await expect(popup.getByRole("status")).toHaveText("已加入生词本。");

  await page.goto("/vocab/mine");
  await expect(page.getByTestId("mine-abandon")).toContainText("手动添加 · 未开始");
});
