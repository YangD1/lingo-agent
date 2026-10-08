import { expect, test } from "@playwright/test";

import { register, uniqueEmail, useFakeModel } from "./helpers";

test.use({ locale: "zh-CN" });

// Two NASA articles are seeded (e2e/run_backend.py); the fake model rewrites the rover
// one as a text with five questions whose right options start "The rover" (e2e/fake_llm.py).
const ROVER = "Engineers test a new rover";
const STATION = "A note from the space station";

test("reading: list → rewritten for my level → add a word → questions → dashboard → ask the tutor", async ({
  page,
}) => {
  await register(page, uniqueEmail());
  await useFakeModel(page);

  await page.getByRole("navigation", { name: "主导航" }).getByRole("link", { name: "阅读" }).click();
  await expect(page).toHaveURL(/\/reading$/);
  await expect(page.getByRole("link", { name: new RegExp(STATION) })).toContainText("只有摘要");
  await page.getByRole("link", { name: new RegExp(ROVER) }).click();
  await expect(page).toHaveURL(/\/reading\/\d+$/);

  // Nobody at A2 has opened it yet: it is rewritten now, the original shown meanwhile.
  await expect(page.getByTestId("reading-title")).toHaveText("Rover news", { timeout: 30_000 });
  await expect(page.getByTestId("reading-license")).toContainText("按你的等级改写自");
  await expect(page.getByTestId("reading-legend")).toContainText("2 个超出你等级的词");
  const ubiquitous = page.getByTestId("reading-text").locator('[data-word="ubiquitous"]').first();
  await expect(ubiquitous).toHaveAttribute("data-glossary", "true");

  // Words open the same popup as in chat.
  await ubiquitous.hover();
  const popup = page.getByTestId("word-popup");
  await expect(popup).toBeVisible();
  await popup.getByRole("button", { name: "加入生词本" }).click();
  await expect(popup.getByRole("status")).toHaveText("已加入生词本。");
  await page.mouse.move(0, 0);

  // Answering needs every question; the right option is shown with its evidence.
  const questions = page.getByTestId("reading-question");
  await expect(questions).toHaveCount(5);
  await expect(page.getByTestId("reading-submit")).toBeDisabled();
  for (let i = 0; i < 5; i++) {
    const question = questions.nth(i);
    const option = i < 4 ? /^The rover/ : /^It can fly/;
    await question.getByRole("radio", { name: option }).check();
  }
  await page.getByTestId("reading-submit").click();
  await expect(page.getByTestId("reading-score")).toContainText("答对 4 / 5");
  await expect(page.getByTestId("reading-score")).toContainText("这次计入你的阅读能力。");
  await expect(questions.last()).toContainText("原文依据：");

  // Opening it again shows the last result, and the list marks it read.
  await page.reload();
  await expect(page.getByTestId("reading-score")).toContainText("答对 4 / 5", { timeout: 15_000 });
  await page.getByRole("link", { name: "全部文章" }).click();
  await expect(page.getByRole("link", { name: new RegExp(ROVER) })).toContainText("读过");
  await expect(page.getByRole("link", { name: new RegExp(ROVER) })).toContainText("已为你改写");

  await page.goto("/vocab/mine");
  await expect(page.getByTestId("mine-ubiquitous")).toBeVisible();

  // The answers count toward the reading skill on the dashboard.
  await page.goto("/dashboard");
  await expect(page.getByTestId("dashboard-skill-reading")).not.toContainText("未评估");

  // Asking the tutor opens a conversation that can see the article.
  await page.goto("/reading");
  await page.getByRole("link", { name: new RegExp(ROVER) }).click();
  await page.getByTestId("reading-ask").click();
  await expect(page).toHaveURL(/\/chat\?c=/);
  const input = page.getByRole("textbox", { name: /输入消息/ });
  await input.fill("What does ubiquitous mean?");
  await input.press("Enter");
  await expect(page.getByText('About "Rover news": you asked What does ubiquitous mean?')).toBeVisible({
    timeout: 30_000,
  });
});

test("reading: the original, and a summary-only article read at its source", async ({ page }) => {
  await register(page, uniqueEmail());
  await useFakeModel(page);

  await page.goto("/reading");
  await page.getByRole("link", { name: new RegExp(ROVER) }).click();
  await expect(page.getByTestId("reading-title")).toHaveText("Rover news", { timeout: 30_000 });
  await page.getByTestId("reading-view").getByText("原文").click();
  await expect(page.getByTestId("reading-title")).toHaveText(ROVER);
  await expect(page.getByTestId("reading-license")).toContainText("原文来自");
  await expect(page.getByTestId("reading-text")).toContainText("Engineers tested a new rover");
  await expect(page.getByTestId("reading-text").locator("[data-glossary]")).toHaveCount(0);

  await page.getByRole("link", { name: "全部文章" }).click();
  await page.getByRole("link", { name: new RegExp(STATION) }).click();
  await expect(page.getByText("这个来源只给摘要，全文请到原网站阅读。")).toBeVisible();
  await expect(page.getByRole("link", { name: "去原网站阅读" })).toHaveAttribute(
    "href",
    "https://www.nasa.gov/e2e-station",
  );
  await expect(page.getByTestId("reading-quiz")).toHaveCount(0);
});
