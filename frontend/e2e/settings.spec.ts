import { expect, test } from "@playwright/test";

import { FAKE_LLM_URL, register, uniqueEmail } from "./helpers";

test.use({ locale: "zh-CN" });

test("configure a model entirely in the UI, chat, and see the usage", async ({ page }) => {
  await register(page, uniqueEmail());
  await page.goto("/settings");
  await expect(page.getByText("还没有连接")).toBeVisible();

  // Add a custom OpenAI-compatible connection pointing at the fake model.
  await page.getByLabel("服务商").selectOption({ label: "自定义（OpenAI 兼容等）" });
  await page.getByLabel("名称").fill("fake");
  await page.getByLabel("Base URL").fill(FAKE_LLM_URL);
  await page.locator("#api_key").fill("sk-fake-1234");
  await page.getByRole("button", { name: "添加连接" }).click();

  const connection = page.getByTestId("connection-fake");
  await expect(connection).toContainText("密钥 …1234");
  await expect(connection).toContainText("尚未测试");

  await connection.getByLabel("测试用的模型").fill("fake-tutor");
  await connection.getByRole("button", { name: "测试" }).click();
  await expect(connection.getByRole("status")).toContainText("连接成功");
  await expect(connection).toContainText("上次测试通过");

  // Route chat to it.
  await page.getByRole("button", { name: "编辑" }).click();
  await page.getByLabel("对话模型，每行一个").fill("fake:fake-tutor");
  await page.getByRole("button", { name: "保存" }).click();
  await expect(page.getByRole("list", { name: "对话模型" })).toHaveText(["fake:fake-tutor"]);
  await expect(page.getByText("正在使用你自定义的顺序")).toBeVisible();

  // Chat works now.
  await page.getByRole("link", { name: "对话" }).click();
  await page.getByRole("textbox", { name: /输入消息/ }).fill("I has a cat");
  await page.getByRole("textbox", { name: /输入消息/ }).press("Enter");
  await expect(page.getByRole("list", { name: "消息" }).locator("li").nth(1)).toHaveText(
    "Nice try! You said: I has a cat",
  );

  // Usage: the connection test + the chat reply, recorded asynchronously.
  await page.getByRole("link", { name: "设置" }).click();
  const usage = page.getByRole("table", { name: "用量" });
  await expect(async () => {
    await page.getByRole("button", { name: "刷新" }).click();
    await expect(usage.locator("tbody tr")).toHaveCount(1, { timeout: 1000 });
    await expect(usage.locator("tbody tr td").nth(2)).toHaveText("2", { timeout: 1000 });
  }).toPass({ timeout: 15_000 });
  await expect(usage.locator("tbody tr td").nth(1)).toHaveText("fake:fake-tutor");
  await expect(usage.locator("tbody tr td").nth(3)).toHaveText("84"); // 42 prompt tokens x 2

  // Reset the route and delete the connection.
  await page.getByRole("button", { name: "恢复默认" }).click();
  await expect(page.getByText("正在使用服务器配置里的默认顺序")).toBeVisible();
  page.once("dialog", (dialog) => dialog.accept());
  await connection.getByRole("button", { name: "删除" }).click();
  await expect(connection).toHaveCount(0);
});

test("adding a preset only needs a key, and bad input is explained", async ({ page }) => {
  await register(page, uniqueEmail());
  await page.goto("/settings");

  await page.getByLabel("服务商").selectOption({ label: "DeepSeek" });
  await page.locator("#api_key").fill("sk-not-a-real-key-9876");
  await page.getByRole("button", { name: "添加连接" }).click();
  await expect(page.getByTestId("connection-deepseek")).toContainText("密钥 …9876");
  // The default chat route starts with deepseek, which now exists: no "skipped" note on it.
  await expect(
    page.getByRole("list", { name: "对话模型" }).locator("li").first(),
  ).toHaveText("deepseek:deepseek-chat");

  // A key-requiring kind without a key is rejected by the backend, with its reason.
  await page.getByLabel("服务商").selectOption({ label: "自定义（OpenAI 兼容等）" });
  await page.getByLabel("名称").fill("mine");
  await page.getByLabel("API 类型").selectOption("openai");
  await page.getByLabel("Base URL").fill("https://api.openai.com/v1");
  await page.getByRole("button", { name: "添加连接" }).click();
  await expect(page.getByRole("form", { name: "添加连接" }).getByRole("alert")).toContainText(
    "模型配置无效。 (openai connections need an API key)",
  );
});
