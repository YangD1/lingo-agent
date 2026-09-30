import { expect, type Page, test } from "@playwright/test";

import { register, uniqueEmail, useFakeModel } from "./helpers";

test.use({ locale: "zh-CN" });

const KC = "g.present_simple_third_person";
const messages = (page: Page) =>
  page.getByRole("list", { name: "消息" }).locator(':scope > li > [data-slot="message"]');
const conversations = (page: Page) => page.getByRole("list", { name: "会话列表" }).locator("li");

async function say(page: Page, text: string) {
  const input = page.getByRole("textbox", { name: /输入消息/ });
  await input.fill(text);
  await input.press("Enter");
  await expect(page.getByRole("button", { name: /^私教做了什么：/ }).last()).toContainText(
    "标记 1 个语法错误",
    { timeout: 15_000 },
  );
}

// The fake model opens practice with the point it finds in the guidance (e2e/fake_llm.py).
test("practice: from the advice into a conversation the tutor opens", async ({ page }) => {
  await register(page, uniqueEmail());
  await useFakeModel(page);
  await page.goto("/chat");
  await say(page, "She like music.");

  await page.getByRole("link", { name: "看板", exact: true }).click();
  const advice = page.getByTestId("advice");
  await advice.getByRole("button", { name: "刷新建议" }).click();
  const practice = advice.getByTestId("advice-item").filter({ hasText: "趁热练一练" });
  await practice.getByRole("link", { name: "开始练习" }).click();

  // A new practice conversation, and the tutor speaks first about the point.
  await expect(page).toHaveURL(/\/chat\?c=[0-9a-f-]{36}$/);
  const id = new URL(page.url()).searchParams.get("c");
  await expect(page.getByTestId("practice-bar")).toContainText(
    "语法练习：一般现在时第三人称单数 -s",
  );
  await expect(messages(page)).toHaveCount(1);
  await expect(messages(page).first()).toContainText(
    "Let's practise: Present simple third-person -s.",
  );
  await expect(page.getByRole("button", { name: /^私教做了什么：/ })).toContainText(
    "按练习要求回复",
  );
  const listed = conversations(page).filter({ hasText: "练习：一般现在时第三人称单数 -s" });
  await expect(listed.getByLabel("语法练习")).toBeVisible();

  // Coming back before saying anything returns to it, without a second opening.
  await page.goto(`/chat?practice=${KC}`);
  await expect(page).toHaveURL(`/chat?c=${id}`);
  await expect(messages(page).first()).toContainText("Let's practise");
  await expect(messages(page)).toHaveCount(1);
  await expect(conversations(page)).toHaveCount(2);

  // The learner's sentences here are evidence like any other conversation's.
  await say(page, "He like tea.");
  await page.getByTestId("practice-bar").getByRole("link", { name: "查看依据" }).click();
  await expect(page).toHaveURL(`/learner?kc=${KC}`);
  const point = page.getByTestId(`kc-${KC}`);
  await expect(point).toContainText("错误 2 次");

  // Once they have spoken, practising again starts afresh.
  await point.getByRole("link", { name: "和私教练一练" }).click();
  await expect(page).toHaveURL(/\/chat\?c=[0-9a-f-]{36}$/);
  expect(new URL(page.url()).searchParams.get("c")).not.toBe(id);
  await expect(messages(page).first()).toContainText("Let's practise");
});
