import { expect, type Page, test } from "@playwright/test";

import { register, uniqueEmail, useFakeModel } from "./helpers";

test.use({ locale: "zh-CN" });

// The fake model tags "she like" as a third-person -s mistake and "he likes" as a
// correct use of the same grammar point (e2e/fake_llm.py).
const KC_NAME = "一般现在时第三人称单数 -s";
const input = (page: Page) => page.getByRole("textbox", { name: /输入消息/ });
const replies = (page: Page) =>
  page.getByRole("list", { name: "消息" }).locator(':scope > li[data-role="assistant"]');
const activityOf = (reply: ReturnType<Page["locator"]>) =>
  reply.getByRole("button", { name: /^私教做了什么：/ });

async function send(page: Page, text: string) {
  await input(page).fill(text);
  await input(page).press("Enter");
  await expect(page.getByRole("button", { name: "发送" })).toBeVisible();
}

test("mistakes in chat show up in the learner model, and can be deleted", async ({ page }) => {
  page.on("dialog", (dialog) => void dialog.accept());
  await register(page, uniqueEmail());
  await useFakeModel(page);

  await page.getByRole("link", { name: "学习者模型" }).click();
  await expect(page.getByText(/还没有记录/)).toBeVisible();
  await expect(page.getByText(/还没有技能估计/)).toBeVisible();

  await page.getByRole("link", { name: "对话" }).click();
  await send(page, "She like music.");
  await expect(activityOf(replies(page).first())).toContainText("标记 1 个语法错误", {
    timeout: 15_000,
  });
  await send(page, "He likes tea.");
  await expect(activityOf(replies(page).nth(1))).toContainText("用对 1 个语法点", {
    timeout: 15_000,
  });
  const conversationUrl = page.url();

  // From the chat straight to the grammar point, opened.
  await activityOf(replies(page).first()).click();
  await replies(page).first().getByRole("link", { name: `${KC_NAME}（A1）` }).click();
  await expect(page).toHaveURL(/\/learner\?kc=g\.present_simple_third_person$/);
  const item = page.getByTestId("kc-g.present_simple_third_person");
  await expect(item.getByRole("button", { name: new RegExp(KC_NAME) })).toHaveAttribute(
    "aria-expanded",
    "true",
  );
  const evidence = item.getByRole("list", { name: "依据" });
  await expect(evidence.getByRole("listitem")).toHaveCount(2);
  await expect(evidence.getByText("She like", { exact: true })).toHaveClass(/line-through/);
  await expect(evidence.getByText("用对了")).toBeVisible();
  await expect(evidence.getByRole("link", { name: /来自“/ }).first()).toHaveAttribute(
    "href",
    `/chat?c=${new URL(conversationUrl).searchParams.get("c")}`,
  );
  await expect(item).toContainText("错误 1 次 · 自由表达用对 1 次");

  // The tag was wrong: delete it. The mastery is recomputed from what is left.
  await evidence
    .getByRole("listitem")
    .filter({ has: page.getByText("She like", { exact: true }) })
    .getByRole("button", { name: "删除这条记录" })
    .click();
  await expect(evidence.getByRole("listitem")).toHaveCount(1);
  await expect(item).toContainText("错误 0 次 · 自由表达用对 1 次");

  // ...and the chat no longer shows it.
  await page.goto(conversationUrl);
  await expect(activityOf(replies(page).nth(1))).toContainText("用对 1 个语法点");
  await expect(activityOf(replies(page).first())).not.toContainText("语法错误");

  // Delete everything: the grammar tags under replies go too.
  await page.goto("/learner");
  await page.getByRole("button", { name: "删除所有学习记录" }).click();
  await expect(page.getByText(/还没有记录/)).toBeVisible();
  await page.goto(conversationUrl);
  await expect(activityOf(replies(page).nth(1))).toBeVisible();
  await expect(activityOf(replies(page).nth(1))).not.toContainText("用对");
});
