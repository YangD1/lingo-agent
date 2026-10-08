import { expect, test } from "@playwright/test";

import { answerPractice as answer, register, uniqueEmail, useFakeModel } from "./helpers";

test.use({ locale: "zh-CN" });

const KC = "g.present_simple_third_person";

test("practice set: written, checked, answered, graded, summed up", async ({ page }) => {
  await register(page, uniqueEmail());
  await useFakeModel(page);

  await page.getByRole("navigation", { name: "主导航" }).getByRole("link", { name: "语法练习" }).click();
  await expect(page).toHaveURL(/\/practice$/);
  await expect(page.getByTestId("practice-landing")).toBeVisible();
  await expect(page.getByText("还没有练习记录。")).toBeVisible();
  await page.getByTestId("practice-start").click();

  // Written and checked by the fake model in the background, then one item per screen.
  await expect(page.getByTestId("practice-item")).toBeVisible({ timeout: 30_000 });
  const progress = page.getByTestId("practice-progress");
  const total = Number((await progress.textContent())?.match(/\/ (\d+)/)?.[1]);
  expect(total).toBeGreaterThanOrEqual(5);

  // The first item is reported instead of answered.
  await page.getByRole("button", { name: "这题有问题" }).click();
  await page.getByRole("group", { name: /标记这题有问题/ }).getByRole("button", { name: "标记" }).click();
  await expect(page.getByTestId("practice-reported")).toBeVisible();
  await page.getByTestId("practice-next").click();

  let wrong = 0;
  for (let n = 2; n <= total; n++) {
    await expect(progress).toHaveText(`第 ${n} / ${total} 题`);
    const format = await answer(page, wrong === 0);
    const verdict = page.getByTestId("practice-verdict");
    if (format === "translate" && wrong === 0) {
      wrong = 1;
      await expect(verdict).toHaveAttribute("data-correct", "false");
      await expect(verdict).toContainText("改正： She walks to work.");
      await expect(verdict).toContainText("The verb needs -s");
    } else {
      await expect(verdict).toHaveAttribute("data-correct", "true");
    }
    await page.keyboard.press("Enter");
  }

  const summary = page.getByTestId("practice-summary");
  await expect(summary).toBeVisible();
  await expect(page.getByTestId("practice-score")).toHaveText(
    `答对 ${total - 1 - wrong} / ${total - 1} 题`,
  );
  await expect(page.getByTestId("practice-made-by")).toContainText("fake:fake-tutor");
  await expect(summary.locator("[data-testid^=practice-kc-]").first()).toContainText("第一次练");

  // The next set was prepared while this one was answered: it starts at once.
  await page.getByTestId("practice-again").click();
  await expect(page.getByTestId("practice-item")).toBeVisible({ timeout: 5_000 });
  await expect(progress).toHaveText(/^第 1 \//);

  // Back on the landing page: the finished set and the one now in progress.
  await page.goto("/practice");
  const recent = page.getByTestId("practice-recent");
  await expect(recent).toHaveCount(2);
  await expect(recent.nth(1)).toContainText(`答对 ${total - 1 - wrong} / ${total - 1}`);
  await expect(recent.nth(0).getByRole("button", { name: /^继续/ })).toBeVisible();
  await expect(page.getByTestId("practice-start")).toHaveText("继续上次的练习");
});

test("practice set: one grammar point from the learner model, with its progress", async ({ page }) => {
  await register(page, uniqueEmail());
  await useFakeModel(page);

  // A mistake in conversation puts the point on the learner model.
  const input = page.getByRole("textbox", { name: /输入消息/ });
  await input.fill("She like music.");
  await input.press("Enter");
  await expect(page.getByRole("button", { name: /^私教做了什么：/ }).last()).toContainText(
    "标记 1 个语法错误",
    { timeout: 15_000 },
  );

  await page.goto(`/learner?kc=${KC}`);
  const point = page.getByTestId(`kc-${KC}`);
  await expect(point.getByTestId("kc-learned-progress")).toContainText("答对的题型 0 / 3 种");
  await point.getByRole("link", { name: "做一组题" }).click();

  await expect(page).toHaveURL(`/practice?from=learner&kc=${KC}`);
  await expect(page.getByTestId("practice-focus")).toContainText("一般现在时第三人称单数 -s");
  await expect(page.getByTestId("practice-item")).toBeVisible({ timeout: 30_000 });
  const total = Number(
    (await page.getByTestId("practice-progress").textContent())?.match(/\/ (\d+)/)?.[1],
  );
  for (let n = 1; n <= total; n++) {
    await answer(page, false);
    await page.keyboard.press("Enter");
  }
  await expect(page.getByTestId("practice-summary")).toBeVisible();
  await expect(page.getByTestId(`practice-kc-${KC}`)).toBeVisible();

  await page.goto(`/learner?kc=${KC}`);
  await expect(point.getByTestId("kc-learned-progress")).not.toContainText("答对的题型 0 / 3 种");
});
