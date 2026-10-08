import { expect, type Page, test } from "@playwright/test";

import { answerPractice, register, uniqueEmail, useFakeModel } from "./helpers";

test.use({ locale: "zh-CN" });

const KC = "g.present_simple_third_person";
const KC_NAME = "一般现在时第三人称单数 -s";

async function say(page: Page, text: string, n: number) {
  const input = page.getByRole("textbox", { name: /输入消息/ });
  await input.fill(text);
  await input.press("Enter");
  await expect(page.getByRole("button", { name: /^私教做了什么：/ }).nth(n)).toContainText(
    "标记 1 个语法错误",
    { timeout: 15_000 },
  );
}

test("tutor's diagnosis: after a practice set, shown on the learner model, deletable", async ({
  page,
}) => {
  await register(page, uniqueEmail());
  await useFakeModel(page);

  await page.goto("/learner");
  const card = page.getByTestId("learner-diagnosis");
  await expect(card).toContainText("每周看一次，做完一组练习后也会看");

  // Three mistakes on one grammar point (the fake model tags "he/she like" each time).
  await page.goto("/chat");
  await say(page, "She like music.", 0);
  await say(page, "He like tea.", 1);
  await say(page, "She like dogs.", 2);

  // Finishing a set diagnoses in the background (e2e/fake_llm.py answers DiagnosisOut).
  await page.goto(`/practice?from=learner&kc=${KC}`);
  await expect(page.getByTestId("practice-item")).toBeVisible({ timeout: 30_000 });
  const total = Number(
    (await page.getByTestId("practice-progress").textContent())?.match(/\/ (\d+)/)?.[1],
  );
  for (let n = 1; n <= total; n++) {
    await answerPractice(page, false);
    await page.keyboard.press("Enter");
  }
  await expect(page.getByTestId("practice-summary")).toBeVisible();

  await expect(async () => {
    await page.goto("/learner");
    await expect(card).toContainText("主语是第三人称单数时", { timeout: 2_000 });
  }).toPass({ timeout: 30_000 });
  await expect(card).toContainText("练习会优先出这些语法点的题");
  await expect(card).toContainText("把握：高");
  await expect(card.getByRole("link", { name: "做一组题" })).toHaveAttribute(
    "href",
    `/practice?from=learner&kc=${KC}`,
  );

  // The cited mistakes, with where they were made.
  await card.getByRole("button", { name: /看引用的 3 条错句/ }).click();
  const cited = card.getByRole("list", { name: "引用的错句" });
  await expect(cited.getByRole("listitem")).toHaveCount(3);
  await expect(cited).toContainText("She like");
  await expect(cited.getByRole("link", { name: /^来自“/ }).first()).toHaveAttribute(
    "href",
    /^\/chat\?c=/,
  );

  // The grammar point it lies in opens in the list below.
  await card.getByRole("button", { name: new RegExp(KC_NAME) }).click();
  await expect(page.getByTestId(`kc-${KC}`).getByTestId("kc-learned-progress")).toBeVisible();

  // The diagnosis left a memory the learner can see.
  await page.goto("/memory");
  await expect(page.getByText(/私教的诊断：主语是第三人称单数时/)).toBeVisible();

  // "This diagnosis is wrong": gone, with its memory.
  await page.goto("/learner");
  await card.getByRole("button", { name: "这次诊断不对" }).click();
  await page.getByRole("alertdialog").getByRole("button", { name: "删除" }).click();
  await expect(card).toContainText("每周看一次，做完一组练习后也会看");
  await page.goto("/memory");
  await expect(page.getByText(/私教的诊断/)).toHaveCount(0);
});
