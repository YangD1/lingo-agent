import { expect, test } from "@playwright/test";

import { FAKE_LLM_URL, register, uniqueEmail, useFakeModel } from "./helpers";

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

  // The model list is fetched right away; the first chat model is preselected.
  await expect(connection.getByTestId("model-list-status")).toHaveText(
    "密钥可用：共 2 个对话模型可选。",
  );
  const model = connection.getByLabel("默认对话模型");
  await expect(model).toHaveValue("fake-tutor");
  // Opening the list offers every chat model, not just the ones matching the current value.
  await model.fill("fake-tutor-mini");
  await model.press("Tab");
  await model.click();
  await expect(page.getByRole("listbox").getByRole("option")).toHaveText(["fake-tutor", "fake-tutor-mini"]);
  // Typing filters it; embedding models are never offered.
  await model.fill("mini");
  await expect(page.getByRole("listbox").getByRole("option")).toHaveText(["fake-tutor-mini"]);
  await model.fill("");
  await expect(page.getByRole("listbox").getByRole("option")).toHaveText(["fake-tutor", "fake-tutor-mini"]);
  await page.getByRole("option", { name: "fake-tutor", exact: true }).click();
  await expect(model).toHaveValue("fake-tutor");
  await connection.getByRole("button", { name: "保存模型" }).click();
  await expect(connection.getByRole("status")).toHaveText("默认模型已保存。");
  await expect(connection.getByRole("button", { name: "保存模型" })).toBeDisabled();

  await connection.getByRole("button", { name: "测试" }).click();
  await expect(connection.getByRole("status")).toContainText("连接成功");
  await expect(connection).toContainText("上次测试通过");

  // No route needed: the connection's default model is used automatically.
  const route = page.getByRole("list", { name: "对话模型" }).getByRole("listitem");
  await expect(page.getByTestId("route-source")).toHaveText(
    "自动：按添加连接的先后，使用各连接的默认模型。",
  );
  await expect(route).toHaveText(["fake:fake-tutor"]);

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

  // Custom order, all with dropdowns: switch row 1 to the mini model, add a fallback
  // (prefilled with the connection's default model), then move it to the top.
  await page.getByRole("button", { name: "调整顺序" }).click();
  const model1 = page.getByLabel("模型 1");
  await expect(page.getByLabel("连接 1")).toHaveValue("fake");
  await expect(model1).toHaveValue("fake-tutor");
  await model1.fill("mini");
  await page.getByRole("option", { name: "fake-tutor-mini" }).click();
  await page.getByRole("button", { name: "+ 添加备用模型" }).click();
  await expect(page.getByLabel("模型 2")).toHaveValue("fake-tutor");
  await page.getByRole("button", { name: "上移" }).nth(1).click();
  await page.getByRole("button", { name: "保存", exact: true }).click();
  await expect(route).toHaveText(["fake:fake-tutor", "fake:fake-tutor-mini"]);
  await expect(page.getByTestId("route-source")).toHaveText("正在使用你自定义的顺序。");

  // Reset the route, then delete the connection: nothing is usable any more.
  await page.getByRole("button", { name: "恢复默认" }).click();
  await expect(page.getByTestId("route-source")).toHaveText(
    "自动：按添加连接的先后，使用各连接的默认模型。",
  );
  page.once("dialog", (dialog) => dialog.accept());
  await connection.getByRole("button", { name: "删除" }).click();
  await expect(connection).toHaveCount(0);
  await expect(page.getByTestId("route-source")).toHaveText(
    "还没有可用的对话模型。请添加连接并保存它的默认模型。",
  );
});

test("when the model list can't be fetched, the reason is shown and a name can be typed", async ({
  page,
}) => {
  await register(page, uniqueEmail());
  await page.goto("/settings");

  // The fake server has no /v1/nope/models: the vendor's 404 is what the user sees.
  await page.getByLabel("服务商").selectOption({ label: "自定义（OpenAI 兼容等）" });
  await page.getByLabel("名称").fill("relay");
  await page.getByLabel("Base URL").fill(`${FAKE_LLM_URL}/nope`);
  await page.locator("#api_key").fill("sk-fake-5678");
  await page.getByRole("button", { name: "添加连接" }).click();

  const connection = page.getByTestId("connection-relay");
  await expect(connection.getByTestId("model-list-status")).toContainText("获取模型列表失败：");
  await expect(connection.getByTestId("model-list-status")).toContainText("404");
  await connection.getByLabel("默认对话模型").fill("my-model");
  await connection.getByLabel("默认对话模型").press("Tab"); // close the (empty) suggestion popup
  await connection.getByRole("button", { name: "保存模型" }).click();
  await expect(connection.getByRole("status")).toHaveText("默认模型已保存。");
  await expect(
    page.getByRole("list", { name: "对话模型" }).getByRole("listitem"),
  ).toHaveText(["relay:my-model"]);
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

test("an existing connection's model list offers everything, and typing filters it", async ({
  page,
}) => {
  await register(page, uniqueEmail());
  await useFakeModel(page); // saved with default model "fake-tutor"
  await page.goto("/settings");
  const model = page.getByTestId("connection-fake").getByLabel("默认对话模型");
  const options = page.getByRole("listbox").getByRole("option");

  // The current value doesn't filter the list: every other model is one click away.
  await model.click();
  await expect(options).toHaveText(["fake-tutor", "fake-tutor-mini"]);
  await page.keyboard.press("Escape");
  await expect(page.getByRole("listbox")).toHaveCount(0);

  // Typing (which reopens the list) filters from the first key.
  await page.keyboard.press("End");
  await page.keyboard.type("-m");
  await expect(options).toHaveText(["fake-tutor-mini"]);
  await options.first().click();
  await expect(model).toHaveValue("fake-tutor-mini");
});
