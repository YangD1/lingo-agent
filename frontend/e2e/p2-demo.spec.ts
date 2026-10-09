import { expect, type Page, test } from "@playwright/test";

import {
  answerOne,
  answerPractice,
  register,
  uniqueEmail,
  useFakeModel,
} from "./helpers";

test.use({ locale: "zh-CN" });

// The whole of P2 in one learner's day (task 49, Q49a), on the fake model: placement →
// today's plan → its essay, practice set and article → the tutor's diagnosis on the
// learner model. Each step has its own spec; this one checks they add up.

const KC = "g.present_simple_third_person";
// The fake model marks each "she like" (e2e/fake_llm.py).
const ESSAY = [
  "My sister is a nurse and she works at night.",
  "On weekends she like music and long walks in the park.",
  "We often cook dinner together and talk about our week.",
].join(" ");

async function say(page: Page, text: string, n: number): Promise<void> {
  const input = page.getByRole("textbox", { name: /输入消息/ });
  await input.fill(text);
  await input.press("Enter");
  await expect(page.getByRole("button", { name: /^私教做了什么：/ }).nth(n)).toContainText(
    "标记 1 个语法错误",
    { timeout: 15_000 },
  );
}

/** Follow one item of today's plan from the dashboard. */
async function openPlanItem(page: Page, kind: string, link: string): Promise<void> {
  await page.goto("/dashboard");
  await page.getByTestId(`plan-item-${kind}`).getByRole("link", { name: link }).click();
}

test("P2 demo: placement, today's plan carried out, diagnosis on the learner model", async ({
  page,
}) => {
  test.setTimeout(180_000);
  await register(page, uniqueEmail());
  await useFakeModel(page);

  // 1. Placement.
  await page.goto("/placement");
  await page.getByRole("button", { name: "开始", exact: true }).click();
  while (!(await page.getByTestId("placement-result").isVisible())) await answerOne(page);
  await expect(page.getByTestId("placement-level")).toHaveText(/^(A1|A2|B1|B2|C1|C2)$/);

  // 2. Today's plan: the essay switched on, then confirmed.
  await page.goto("/dashboard");
  const plan = page.getByTestId("today-plan");
  await expect(plan).toHaveAttribute("data-status", "proposed");
  await plan.getByTestId("plan-row-writing").getByRole("switch").click();
  await plan.getByRole("button", { name: "确认计划" }).click();
  await expect(plan).toHaveAttribute("data-status", "applied");
  await expect(plan).toContainText("完成 0/3");

  // 3. The essay: one mistake on the third-person -s.
  await openPlanItem(page, "writing", "去写");
  await page.getByRole("button", { name: "不写题目" }).click();
  await page.getByTestId("writing-text").fill(ESSAY);
  await page.getByTestId("writing-submit").click();
  await expect(page.getByTestId("writing-summary")).toContainText(
    "1 处语法错误，已记入学习者模型",
    { timeout: 30_000 },
  );

  // Two more in conversation: enough for a diagnosis (rules.yaml diagnosis.min_mistakes).
  await page.goto("/chat");
  await say(page, "He like tea.", 0);
  await say(page, "She like dogs.", 1);

  // 4. The plan's practice set; finishing it diagnoses in the background.
  await openPlanItem(page, "practice", "去练习");
  await expect(page).toHaveURL(/\/practice\?from=plan&kc=g\./);
  await expect(page.getByTestId("practice-item")).toBeVisible({ timeout: 30_000 });
  const total = Number(
    (await page.getByTestId("practice-progress").textContent())?.match(/\/ (\d+)/)?.[1],
  );
  for (let n = 1; n <= total; n++) {
    await answerPractice(page, false);
    await page.keyboard.press("Enter");
  }
  await expect(page.getByTestId("practice-summary")).toBeVisible();

  // 5. The plan's article (never a summary-only one): rewritten, then its questions.
  await openPlanItem(page, "reading", "去读");
  await expect(page.getByTestId("reading-title")).toHaveText("Rover news", { timeout: 30_000 });
  const questions = page.getByTestId("reading-question");
  await expect(questions).toHaveCount(5);
  for (let i = 0; i < 5; i++) {
    await questions.nth(i).getByRole("radio", { name: /^The rover/ }).check();
  }
  await page.getByTestId("reading-submit").click();
  await expect(page.getByTestId("reading-score")).toContainText("答对 5 / 5");

  // 6. The dashboard ticks all three off and has the new skills.
  await page.goto("/dashboard");
  for (const kind of ["writing", "practice", "reading"]) {
    await expect(plan.getByTestId(`plan-item-${kind}`)).toHaveAttribute("data-complete", "true");
  }
  await expect(plan).toContainText("今天的计划都完成了！");
  await expect(page.getByTestId("dashboard-skill-reading")).not.toContainText("未评估");

  // 7. The learner model: the diagnosis, and the point's evidence from writing and chat.
  const card = page.getByTestId("learner-diagnosis");
  await expect(async () => {
    await page.goto("/learner");
    await expect(card).toContainText("主语是第三人称单数时", { timeout: 2_000 });
  }).toPass({ timeout: 30_000 });
  await card.getByRole("button", { name: /看引用的 \d+ 条错句/ }).click();
  const cited = card.getByRole("list", { name: "引用的错句" });
  await expect(cited.getByRole("link", { name: /^来自“/ }).first()).toBeVisible();
  await expect(cited).toContainText("来自写作");

  await page.goto(`/learner?kc=${KC}`);
  await expect(page.getByTestId(`kc-${KC}`)).toBeVisible();
});
