import { expect, type Page, test } from "@playwright/test";

import { register, uniqueEmail, useFakeModel } from "./helpers";

test.use({ locale: "zh-CN" });

/** Learn the first `n` new words of today's queue through the API. */
async function learnNewWords(page: Page, n: number): Promise<void> {
  const queue = (await (await page.request.get("/api/vocab/queue")).json()) as {
    new: { word: { id: number } }[];
  };
  for (const item of queue.new.slice(0, n)) {
    const rated = await page.request.post("/api/vocab/reviews", {
      data: { word_id: item.word.id, rating: 3 },
    });
    expect(rated.status()).toBe(200);
  }
}

// Today's plan (ADR 0027): drafted by code on the dashboard, adjusted and confirmed there,
// replaced by the tutor's card when the learner asks for another (e2e/fake_llm.py proposes
// 3 new words on "只有 10 分钟"), ticked off from what the learner did.
test("today's plan: adjust and confirm, the tutor's lighter plan, progress and undo", async ({
  page,
}) => {
  await register(page, uniqueEmail());
  await page.goto("/dashboard");
  const plan = page.getByTestId("today-plan");

  // A new learner has no word book and no due words: a practice set and one of the
  // seeded articles fit 20 minutes (e2e/run_backend.py seeds the built-in feeds).
  await expect(plan).toHaveAttribute("data-status", "proposed");
  await expect(plan).toContainText("你还没设每天学多久，先按 20 分钟排");
  await expect(plan.getByTestId("plan-row-new_words")).toContainText("还没选词书");
  await expect(plan.getByTestId("plan-total")).toHaveText("预计 18 分钟");
  await plan.getByTestId("plan-row-writing").getByRole("switch").click();
  await expect(plan.getByTestId("plan-total")).toHaveText("预计 33 分钟");
  await plan.getByRole("button", { name: "确认计划" }).click();

  await expect(plan).toHaveAttribute("data-status", "applied");
  await expect(plan).toContainText("完成 0/3");
  await expect(
    plan.getByTestId("plan-item-reading").getByRole("link", { name: "去读" }),
  ).toHaveAttribute("href", /^\/reading\/\d+$/);
  await expect(
    plan.getByTestId("plan-item-practice").getByRole("link", { name: "去练习" }),
  ).toHaveAttribute("href", /^\/practice\?from=plan&kc=g\./);
  await expect(
    plan.getByTestId("plan-item-writing").getByRole("link", { name: "去写" }),
  ).toHaveAttribute("href", "/writing");

  // Later the learner chooses a book and asks the tutor for less: a new plan on a card,
  // within what is open now (the book allows new words), replacing the one above.
  const book = await page.request.put("/api/vocab/book", {
    data: { book_id: "oxford3000", daily_new: null },
  });
  expect(book.status()).toBe(204);
  await useFakeModel(page);
  await page.reload();
  const today = page.getByTestId("today");
  const input = today.getByRole("textbox", { name: /输入消息/ });
  await input.fill("我今天只有 10 分钟");
  await input.press("Enter");
  const card = today.locator("[data-testid=tutor-card][data-kind=daily_plan]");
  await expect(card).toContainText("新的今天计划", { timeout: 15_000 });
  await expect(card.getByTestId("plan-row-new_words")).toContainText("学 3 个新词");
  await expect(card.getByTestId("plan-total")).toHaveText("预计 3 分钟");
  await card.getByRole("button", { name: "确认", exact: true }).click();
  await expect(card).toContainText("已完成。");

  await expect(plan.getByTestId("plan-item-new_words")).toContainText("学 3 个新词");
  await expect(plan.getByTestId("plan-item-practice")).toHaveCount(0);
  await expect(plan).toContainText("私教按你说的改过");
  await expect(plan.getByTestId("plan-item-new_words").getByTestId("plan-progress")).toHaveText(
    "0/3",
  );

  // Studying elsewhere ticks it off.
  await learnNewWords(page, 2);
  await page.reload();
  await expect(plan.getByTestId("plan-item-new_words").getByTestId("plan-progress")).toHaveText(
    "2/3",
  );
  await learnNewWords(page, 1);
  await page.reload();
  await expect(plan.getByTestId("plan-item-new_words")).toHaveAttribute("data-complete", "true");
  await expect(plan).toContainText("今天的计划都完成了！");

  // Undoing the tutor's plan brings back the one confirmed before.
  await plan.getByRole("button", { name: "撤销" }).click();
  await expect(plan.getByTestId("plan-item-practice")).toBeVisible();
  await expect(plan.getByTestId("plan-item-reading")).toBeVisible();
  await expect(plan.getByTestId("plan-item-writing")).toBeVisible();
  await expect(plan.getByTestId("plan-item-new_words")).toHaveCount(0);
  await expect(plan).not.toContainText("私教按你说的改过");
});

test("today's plan: no plan today", async ({ page }) => {
  await register(page, uniqueEmail());
  await page.goto("/dashboard");
  const plan = page.getByTestId("today-plan");
  await plan.getByRole("button", { name: "今天不要计划" }).click();
  await expect(plan.getByTestId("plan-declined")).toContainText("今天不排计划");
  await page.reload();
  await expect(plan.getByTestId("plan-declined")).toBeVisible();
});
