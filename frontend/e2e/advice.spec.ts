import { expect, test } from "@playwright/test";

import { register, uniqueEmail, useFakeModel } from "./helpers";

test.use({ locale: "zh-CN" });

// The fake model picks an invented action and a grammar practice candidate (e2e/fake_llm.py).
test("advice: templates without a model, then only the model's real picks", async ({ page }) => {
  await register(page, uniqueEmail());
  await page.goto("/dashboard");

  // No model yet: the learning engine's candidates, in template text.
  const advice = page.getByTestId("advice");
  const items = advice.getByTestId("advice-item");
  await expect(items).toHaveCount(2);
  await expect(items.nth(0)).toContainText("做一次入学测");
  await expect(items.nth(1)).toContainText("选一本词书");
  await expect(page.getByTestId("advice-status")).toContainText("还没配置模型", {
    timeout: 15_000,
  });
  // No item was written by a model (the title's badge explains the feature itself).
  await expect(items.getByTestId("ai-badge-advice")).toHaveCount(0);

  // A model, and a grammar mistake in chat.
  await useFakeModel(page);
  await page.getByRole("link", { name: "对话", exact: true }).click();
  const input = page.getByRole("textbox", { name: /输入消息/ });
  await input.fill("She like music.");
  await input.press("Enter");
  await expect(page.getByRole("button", { name: /^私教做了什么：/ }).first()).toContainText(
    "标记 1 个语法错误",
    { timeout: 15_000 },
  );

  // The candidates changed only a moment ago: ask for new advice by hand.
  await page.getByRole("link", { name: "看板", exact: true }).click();
  await advice.getByRole("button", { name: "刷新建议" }).click();

  const practice = items.filter({ hasText: "趁热练一练" });
  await expect(practice).toBeVisible({ timeout: 15_000 });
  await expect(practice.getByTestId("ai-badge-advice")).toBeVisible();
  await expect(practice).toContainText("假模型挑了这一条。");
  await expect(practice).toContainText("最近错 1 次");
  // The invented action is dropped; the best other candidates fill in as templates.
  await expect(items).toHaveCount(3);
  await expect(advice).not.toContainText("Made up");
  await expect(items.nth(1)).toContainText("做一次入学测");
  await expect(items.nth(2)).toContainText("选一本词书");
  await expect(advice).toContainText("由 AI 从学习引擎给出的候选里挑选");
  await expect(advice.getByRole("button", { name: "刷新建议" })).toBeDisabled();
  await expect(advice).toContainText("分钟后可再刷新");

  // Practice starts a conversation (e2e/practice.spec.ts); the evidence is a link away.
  await expect(practice.getByRole("link", { name: "开始练习" })).toHaveAttribute(
    "href",
    "/chat?practice=g.present_simple_third_person",
  );
  await practice.getByRole("link", { name: "查看依据" }).click();
  await expect(page).toHaveURL(/\/learner\?kc=g\.present_simple_third_person$/);
});
