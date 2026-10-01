import { expect, test } from "@playwright/test";

import { register, uniqueEmail, useFakeModel } from "./helpers";

test.use({ locale: "zh-CN" });

// Today's conversation on the dashboard (ADR 0016 §1–3). The fake model proposes a word
// book when asked about one (e2e/fake_llm.py).
test("today: rule advice without a model, then a quick reply the tutor answers with a card", async ({
  page,
}) => {
  await register(page, uniqueEmail());
  await page.goto("/dashboard");
  const today = page.getByTestId("today");

  // No model yet: the learning engine's candidates as links, and the way to settings.
  const rules = today.getByTestId("today-rules");
  await expect(rules).toContainText("还没配置模型");
  await expect(rules.getByRole("link", { name: "去设置" })).toHaveAttribute("href", "/settings");
  const items = rules.getByTestId("advice-item");
  await expect(items).toHaveCount(2);
  await expect(items.nth(0)).toContainText("做一次入学测");
  await expect(items.nth(1)).toContainText("选一本词书");
  await expect(today.getByTestId("today-quick")).toHaveCount(0);

  // With a model: a greeting and quick replies made by rules; nothing is created yet.
  await useFakeModel(page);
  await page.reload();
  await expect(today.getByTestId("today-greeting")).toContainText("还没做过入学测");
  await expect(today.getByRole("button", { name: "今天学什么？" })).toBeVisible();
  await expect(today.getByRole("button", { name: "我想做入学测" })).toBeVisible();
  await expect(today.getByTestId("today-quick").getByTestId("ai-badge-chat_message")).toBeVisible();
  await expect(today.getByRole("link", { name: "在对话页继续" })).toHaveCount(0);
  expect(await (await page.request.get("/api/conversations")).json()).toEqual([]);

  // A quick reply is the learner's message: the tutor answers it, with a proposal card.
  await today.getByRole("button", { name: "帮我选一本词书" }).click();
  const card = today.getByTestId("tutor-card");
  await expect(card).toContainText("把词书换成 牛津 3000 核心词", { timeout: 15_000 });
  await expect(today.locator("li[data-role=assistant]").first()).toContainText(
    "I've put a suggestion on a card.",
  );
  await expect(today.getByTestId("today-greeting")).toHaveCount(0);
  await card.getByRole("button", { name: "确认" }).click();
  await expect(card).toContainText("已完成。");

  // Coming back shows today's conversation; it is also in the chat list, and continues there.
  await page.reload();
  await expect(page.getByTestId("dashboard-book")).not.toContainText("还没选词书");
  await expect(today.locator("li[data-role=user]").first()).toContainText("帮我选一本词书");
  await expect(today.getByTestId("today-greeting")).toHaveCount(0);
  await today.getByRole("link", { name: "在对话页继续" }).click();
  await expect(page).toHaveURL(/\/chat\?c=[0-9a-f-]{36}$/);
  const listed = page.getByRole("navigation", { name: "会话列表" }).locator("li");
  await expect(listed).toHaveCount(1);
  await expect(listed.first()).toContainText("今天的学习");
});
