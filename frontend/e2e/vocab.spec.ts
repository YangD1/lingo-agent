import { execFileSync } from "node:child_process";

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
  // Flashcards open over the page (ADR 0038).
  await expect(page).toHaveURL(/\/vocab\?review=all$/);
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

  // Closing leaves vocabulary under it, which reloads its counts.
  await done.getByRole("button", { name: "关闭" }).click();
  await expect(page.getByTestId("review-deck")).toHaveCount(0);
  await expect(page).toHaveURL(/\/vocab$/);
  await expect(page.getByTestId("today-counts")).toHaveText(
    "待复习 0 个 · 新词还剩 0 个（今天已开始 5 / 15）",
  );
  await expect(book).toContainText("学习中 5 · 已认识 2 · 已接触 100%");
  await page.reload();
  await expect(book.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "100");
});

test("reviewed words come back to be heard and picked, or spelled (task 63)", async ({ page }) => {
  await register(page, uniqueEmail());
  const chosen = await page.request.put("/api/vocab/book", { data: { book_id: OXFORD } });
  expect(chosen.status()).toBe(204);
  await page.goto("/vocab/review");

  // New words are shown as words whatever the type; miss two so they come back.
  await page.getByRole("radio", { name: "听音" }).click();
  await expect(page.getByTestId("review-format-note")).toContainText("第一次学的词先看词");
  for (const [word, rating] of [
    ["the", "1"],
    ["go", "1"],
    ["us", "4"],
    ["run", "4"],
    ["abandon", "4"],
    ["hello", "4"],
    ["colour", "4"],
  ]) {
    await expect(page.getByRole("heading", { name: word, exact: true })).toBeVisible();
    await page.keyboard.press("Space");
    await page.keyboard.press(rating as string);
  }

  // "the" again: heard, not shown; its meaning among three of the book's others.
  const listen = page.getByTestId("review-listen");
  await expect(listen).toBeVisible();
  await expect(page.getByRole("heading", { name: "the", exact: true })).toHaveCount(0);
  const options = listen.getByRole("group", { name: "选出意思" }).getByRole("button");
  await expect(options).toHaveCount(4);
  await listen.getByRole("button", { name: "art. 那" }).click();
  await expect(page.getByTestId("review-result")).toHaveText("选对了");
  await expect(page.getByRole("button", { name: /记得/ })).toHaveAttribute("data-suggested", "true");
  await page.keyboard.press("Enter");

  // "go" spelled from its sound and meaning.
  await page.getByRole("radio", { name: "拼写" }).click();
  await expect(page.getByTestId("review-spell")).toContainText("vi. 去, 走, 达到");
  const input = page.getByRole("textbox", { name: "写出这个词" });
  await input.fill("goo");
  await input.press("Enter");
  await expect(page.getByTestId("review-result")).toContainText("差一个字母");
  await expect(page.getByTestId("review-result")).toContainText("你写的：goo");
  await expect(page.getByRole("button", { name: /模糊/ })).toHaveAttribute("data-suggested", "true");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("review-progress")).toContainText("已复习 9");

  // The choice is kept in this browser.
  await page.reload();
  await expect(page.getByRole("radio", { name: "拼写" })).toHaveAttribute("aria-checked", "true");
});

test.describe("on a phone", () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });

  /** The card has stopped turning. */
  async function waitForStill(page: Page) {
    await expect
      .poll(() => page.getByTestId("review-card").evaluate((el) => el.getAnimations().length))
      .toBe(0);
  }

  /** A finger drag across the card, through Chromium's touch input. */
  async function swipe(page: Page, dx: number) {
    const box = (await page.getByTestId("review-card").boundingBox())!;
    const x = box.x + box.width / 2;
    const y = box.y + box.height / 3;
    const cdp = await page.context().newCDPSession(page);
    await cdp.send("Input.dispatchTouchEvent", { type: "touchStart", touchPoints: [{ x, y }] });
    for (let i = 1; i <= 8; i++) {
      await cdp.send("Input.dispatchTouchEvent", {
        type: "touchMove",
        touchPoints: [{ x: x + (dx * i) / 8, y }],
      });
    }
    await cdp.send("Input.dispatchTouchEvent", { type: "touchEnd", touchPoints: [] });
    await cdp.detach();
  }

  test("swipe the back of a card left for Again, right for Good (ADR 0038)", async ({ page }) => {
    await register(page, uniqueEmail());
    const chosen = await page.request.put("/api/vocab/book", { data: { book_id: OXFORD } });
    expect(chosen.status()).toBe(204);
    await page.goto("/vocab/review");
    const progress = page.getByTestId("review-progress");

    await expect(page.getByRole("heading", { name: "the", exact: true })).toBeVisible();
    await page.getByRole("button", { name: "显示答案" }).click();
    await expect(page.getByTestId("review-swipe-hint")).toBeVisible();
    await waitForStill(page);
    // Not far enough: it springs back unrated.
    await swipe(page, -30);
    await expect(progress).toContainText("已复习 0");
    await swipe(page, -180);
    await expect(progress).toContainText("已复习 1");

    await expect(page.getByRole("heading", { name: "go", exact: true })).toBeVisible();
    await page.getByRole("button", { name: "显示答案" }).click();
    await waitForStill(page);
    await swipe(page, 180);
    await expect(progress).toContainText("已复习 2");
    await expect(page.getByRole("heading", { name: "us", exact: true })).toBeVisible();

    // The rest by keys; then "the", swiped to Again, comes round again in this sitting.
    for (const word of ["us", "run", "abandon", "hello", "colour"]) {
      await expect(page.getByRole("heading", { name: word, exact: true })).toBeVisible();
      await page.keyboard.press("Space");
      await page.keyboard.press("4");
    }
    await expect(progress).toContainText("已复习 7");
    await expect(page.getByRole("heading", { name: "the", exact: true })).toBeVisible();
  });
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

/** Flip a background switch and wait until the backend has it (the switch moves at once). */
async function flip(page: Page, name: string) {
  const saved = page.waitForResponse(
    (r) => r.url().includes("/me/background/") && r.request().method() === "PUT" && r.ok(),
  );
  await page.locator("#background").getByRole("switch", { name }).click();
  await saved;
}

/** One `word_examples_prefetch` run for this learner only (e2e/prefetch_examples.py). */
function prefetchExamples(email: string) {
  execFileSync("uv", ["run", "--project", "../backend", "python", "e2e/prefetch_examples.py", email], {
    stdio: "inherit",
  });
}

test("AI examples written ahead show when the card turns over, unless switched off (task 44)", async ({
  page,
}) => {
  const email = uniqueEmail();
  await register(page, email);
  await useFakeModel(page);
  await page.goto("/vocab");
  await page.getByTestId(`book-${OXFORD}`).getByRole("button", { name: "学这本" }).click();

  // On by default, with its AI badge. Switched off, nothing is written ahead.
  await page.goto("/settings#background");
  const prefetch = page.locator("#background").getByRole("switch", { name: "预先写好 AI 例句" });
  await expect(prefetch).toBeChecked();
  await expect(
    page.locator("#background").getByTestId("ai-badge-word_examples_prefetch"),
  ).toBeVisible();
  await flip(page, "预先写好 AI 例句");
  await expect(prefetch).not.toBeChecked();
  prefetchExamples(email);

  const examples = page.getByTestId("review-examples");
  const turnOverThe = async () => {
    await page.goto("/vocab/review");
    await expect(page.getByRole("heading", { name: "the", exact: true })).toBeVisible();
    await page.getByRole("button", { name: "显示答案" }).click();
    await expect(examples).toBeVisible();
  };
  await turnOverThe();
  await expect(page.getByTestId("review-ai-examples")).toHaveCount(0);
  await expect(examples.getByRole("button", { name: "AI 例句" })).toBeVisible();

  // On again: the coming new words without a Tatoeba sentence ("the") get sentences,
  // shown at once; "go" has real ones, so none are written for it.
  await page.goto("/settings#background");
  await flip(page, "预先写好 AI 例句");
  await expect(prefetch).toBeChecked();
  prefetchExamples(email);
  await turnOverThe();
  await expect(page.getByTestId("review-ai-examples")).toContainText("I the every day.");
  await expect(examples).toContainText("AI 生成");
  await expect(examples.getByRole("button", { name: "AI 例句" })).toHaveCount(0);
  await page.keyboard.press("4");
  await expect(page.getByRole("heading", { name: "go", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "显示答案" }).click();
  await expect(page.getByTestId("review-ai-examples")).toHaveCount(0);
  await expect(examples.getByRole("button", { name: "AI 例句" })).toBeVisible();
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

test("the tutor's flashcards card opens them over the conversation (ADR 0038)", async ({ page }) => {
  await register(page, uniqueEmail());
  const chosen = await page.request.put("/api/vocab/book", { data: { book_id: OXFORD } });
  expect(chosen.status()).toBe(204);
  await useFakeModel(page);
  await page.goto("/chat");
  await chat(page, "我们来背单词吧");
  const card = page.locator("[data-testid=tutor-card][data-kind=link]");
  await expect(card).toContainText("复习和学新词");
  await expect(page).toHaveURL(/\/chat\?c=[0-9a-f-]{36}$/);
  const conversation = page.url();

  // Over the conversation, keeping it in the address; Back closes it.
  await card.getByRole("link", { name: "去复习" }).click();
  const deck = page.getByTestId("review-deck");
  await expect(deck.getByRole("heading", { name: "the", exact: true })).toBeVisible();
  expect(page.url()).toBe(`${conversation}&review=all`);
  await page.goBack();
  await expect(deck).toHaveCount(0);
  expect(page.url()).toBe(conversation);

  // Esc closes it too, leaving the conversation as it was.
  await card.getByRole("link", { name: "去复习" }).click();
  await expect(deck).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(deck).toHaveCount(0);
  expect(page.url()).toBe(conversation);
  await expect(replies(page)).toHaveCount(1);
});
