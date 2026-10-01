import { expect, test } from "@playwright/test";

import { register, uniqueEmail, useFakeModel } from "./helpers";

test.use({ locale: "zh-CN" });

test("AI badges explain token use, from defaults and then from the tenant's own calls", async ({
  page,
}) => {
  await register(page, uniqueEmail());

  // No model and no history yet: default estimates.
  const send = page.getByTestId("ai-badge-chat_message");
  await send.hover();
  const details = page.getByTestId("ai-badge-details");
  await expect(details).toContainText("私教的回复由 AI 模型生成");
  // Each call: task name with its timing, the estimate, the model, then where it came from.
  await expect(details).toContainText("回复立即");
  await expect(details).toContainText("复盘这一轮回复后在后台");
  await expect(details).toContainText("还没配置模型还没有记录，这是默认估计");
  await expect(details).toContainText("只显示 token 数");
  await page.screenshot({ path: test.info().outputPath("chat-badge-default.png") });

  // The attach button covers images and scanned PDFs; tapping works like hovering.
  await page.mouse.move(0, 0);
  await expect(details).toBeHidden();
  await page.getByTestId("ai-badge-chat_image-chat_pdf").click();
  await expect(details).toContainText("每张图");
  await expect(details).toContainText("每页");
  await page.keyboard.press("Escape");

  // One reply from the fake model (it reports 42 input tokens) becomes the estimate.
  await useFakeModel(page);
  const input = page.getByRole("textbox", { name: /输入消息/ });
  await input.fill("I goed home");
  await input.press("Enter");
  await expect(page.getByText("Nice try! You said: I goed home")).toBeVisible();

  await expect(async () => {
    await page.reload(); // estimates are cached per page load
    await page.getByTestId("ai-badge-chat_message").hover();
    await expect(page.getByTestId("ai-badge-details")).toContainText(
      "约 42 输入 + 7 输出 token",
      { timeout: 2_000 },
    );
  }).toPass({ timeout: 20_000 });
  await expect(page.getByTestId("ai-badge-details")).toContainText(
    "模型 fake:fake-tutor按你最近 1 次调用的平均",
  );
  await page.screenshot({ path: test.info().outputPath("chat-badge-history.png") });
});
