import { expect, type Page, test } from "@playwright/test";

import { register, uniqueEmail, useFakeModel } from "./helpers";

test.use({ locale: "zh-CN" });

/** Settings' "used today" line, reloaded until it matches (usage rows are written in batches). */
async function expectUsedToday(page: Page, text: RegExp) {
  await expect(async () => {
    // Not "#background": going to the same URL with a hash does not reload the page.
    await page.goto("/settings");
    await expect(page.getByText(text)).toBeVisible({ timeout: 1_000 });
  }).toPass({ timeout: 15_000 });
}

/** Finish the set on screen by reporting every item: no grading calls are made. */
async function reportEveryItem(page: Page) {
  await expect(page.getByTestId("practice-item")).toBeVisible({ timeout: 30_000 });
  const progress = page.getByTestId("practice-progress");
  const total = Number((await progress.textContent())?.match(/\/ (\d+)/)?.[1]);
  for (let n = 1; n <= total; n++) {
    await expect(progress).toHaveText(`第 ${n} / ${total} 题`);
    await page.getByRole("button", { name: "这题有问题" }).click();
    await page.getByRole("group", { name: /标记这题有问题/ }).getByRole("button", { name: "标记" }).click();
    await expect(page.getByTestId("practice-reported")).toBeVisible();
    await page.getByTestId("practice-next").click();
  }
  await expect(page.getByTestId("practice-summary")).toBeVisible();
}

test("background work: the learner switches it off, the budget turns it all off (ADR 0025)", async ({
  page,
}) => {
  await register(page, uniqueEmail());
  await useFakeModel(page);

  await page.goto("/settings#background");
  const section = page.locator("#background");
  await expect(section.getByText("后台任务", { exact: true })).toBeVisible();
  const prefetch = section.getByRole("switch", { name: "预先出好下一组练习" });
  await expect(prefetch).toBeChecked();
  await expect(section).toContainText("今天已用 0 / 100,000 token");
  await expect(section).toContainText("还没有定时任务。");
  // The E2E backend runs with SCHEDULER_ENABLED=false.
  await expect(section).toContainText("定时任务没有在运行");

  // Off: finishing a set does not generate the next one in the background.
  await prefetch.click();
  await expect(prefetch).not.toBeChecked();
  await page.goto("/practice");
  await page.getByTestId("practice-start").click();
  await reportEveryItem(page);
  // Long enough for a set generated ahead (seconds with the fake model) and the usage
  // writer's 2 s batches: zero now really means nothing ran in the background.
  await page.waitForTimeout(5_000);
  // The set itself was generated while the learner waited: not background work.
  await expectUsedToday(page, /今天已用 0 \/ 100,000 token/);

  // On again: the next finished set prepares one ahead, which counts as background.
  await page.locator("#background").getByRole("switch", { name: "预先出好下一组练习" }).click();
  await expect(
    page.locator("#background").getByRole("switch", { name: "预先出好下一组练习" }),
  ).toBeChecked();
  await page.goto("/practice");
  await page.getByTestId("practice-start").click();
  await reportEveryItem(page);
  await expectUsedToday(page, /今天已用 [1-9][\d,]* \/ 100,000 token/);

  // A limit of 0 switches all background calls off; the learner is told so.
  await page.getByLabel("每天上限（token）").fill("0");
  await page.locator("#background").getByRole("button", { name: "保存上限" }).click();
  await expect(page.locator("#background")).toContainText("管理员关闭了全部后台调用");
  await expect(page.getByLabel("每天上限（token）")).toHaveValue("0");
});
