import { expect, type Page, test } from "@playwright/test";

import { register, uniqueEmail, useFakeModel } from "./helpers";

test.use({ locale: "zh-CN" });

const input = (page: Page) => page.getByRole("textbox", { name: /输入消息/ });
const reply = (page: Page) =>
  page.getByRole("list", { name: "消息" }).locator(':scope > li > [data-slot="message"]').nth(1);

async function chat(page: Page, text: string) {
  await page.getByRole("link", { name: "对话" }).click();
  await input(page).fill(text);
  await input(page).press("Enter");
}

test("switching models off stops them without losing the settings (ADR 0026)", async ({ page }) => {
  await register(page, uniqueEmail());
  await useFakeModel(page);
  await page.goto("/settings");

  // Switch the only chat model off: it stays in the chain, greyed, and nothing else steps in.
  const card = page.getByTestId("route-chat");
  const row = card.getByRole("listitem");
  await card.getByRole("switch", { name: "使用 fake:fake-tutor" }).click();
  await expect(card.getByRole("status")).toHaveText("已停用 fake:fake-tutor，调用时会跳过它。");
  await expect(row).toHaveAttribute("data-state", "off");
  await expect(row).toContainText("已停用");
  await expect(card).toContainText("这个功能的模型都停用了，打开一个才能使用。");
  await card.screenshot({ path: test.info().outputPath("route-off-light.png") });
  await page.emulateMedia({ colorScheme: "dark" });
  await card.screenshot({ path: test.info().outputPath("route-off-dark.png") });
  await page.emulateMedia({ colorScheme: "light" });

  await chat(page, "I has a cat");
  await expect(page.getByRole("alert").filter({ hasText: "模型都停用了" })).toBeVisible();
  await expect(page.getByRole("link", { name: "去设置" })).toHaveAttribute("href", "/settings");

  // Back on: chat works again, and the chain is now the learner's own.
  await page.getByRole("link", { name: "去设置" }).click();
  await card.getByRole("switch", { name: "使用 fake:fake-tutor" }).click();
  await expect(row).toHaveAttribute("data-state", "on");
  await expect(page.getByTestId("route-source-chat")).toHaveText("正在使用你自定义的顺序。");
  await chat(page, "I has a cat");
  await expect(reply(page)).toHaveText("Nice try! You said: I has a cat");

  // The whole connection off: every chain marks its rows, the key and model are kept.
  await page.getByRole("link", { name: "设置" }).click();
  const connection = page.getByTestId("connection-fake");
  await connection.getByRole("switch", { name: "启用 fake" }).click();
  await expect(connection.getByRole("status")).toHaveText("已停用这个连接。");
  await expect(connection).toContainText("所有功能都不会用这个连接");
  await expect(connection.getByLabel("默认模型")).toHaveValue("fake-tutor");
  await expect(row).toHaveAttribute("data-state", "connectionOff");
  await expect(row).toContainText("连接已停用");
  await connection.screenshot({ path: test.info().outputPath("connection-off-light.png") });
  await page.emulateMedia({ colorScheme: "dark" });
  await connection.screenshot({ path: test.info().outputPath("connection-off-dark.png") });
  await page.emulateMedia({ colorScheme: "light" });

  // Nothing else to fall back to: the usual "set up a model" guidance.
  await chat(page, "Hello again");
  await expect(page.getByRole("alert").filter({ hasText: "还没有配置聊天模型" })).toBeVisible();

  await page.getByRole("link", { name: "去设置" }).click();
  await connection.getByRole("switch", { name: "启用 fake" }).click();
  await expect(row).toHaveAttribute("data-state", "on");
  await expect(connection).not.toContainText("所有功能都不会用这个连接");
});
