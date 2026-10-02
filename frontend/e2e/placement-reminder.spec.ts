import { expect, test } from "@playwright/test";

import { register, uniqueEmail } from "./helpers";

test.use({ locale: "zh-CN" });

test("placement reminder: practice page before a first set, Not now shared with the chat page", async ({
  page,
}) => {
  await register(page, uniqueEmail());
  await expect(page.getByTestId("placement-banner")).toContainText("先做个入学测吧");

  await page.goto("/practice");
  const hint = page.getByTestId("placement-reminder");
  await expect(hint).toContainText("也可以先做一组");
  await expect(hint.getByRole("link", { name: "开始入学测" })).toHaveAttribute("href", "/placement");
  await expect(page.getByTestId("practice-start")).toBeEnabled();

  // "Not now" is kept on the server: gone here after a reload, and on the chat page too.
  await hint.getByRole("button", { name: "以后再说" }).click();
  await expect(hint).toHaveCount(0);
  const asked = () => page.waitForResponse((r) => r.url().endsWith("/api/placement/reminder"));
  let reply = asked();
  await page.reload();
  expect((await (await reply).json()).snoozed).toBe(true);
  await expect(page.getByTestId("practice-landing")).toBeVisible();
  await expect(page.getByTestId("placement-reminder")).toHaveCount(0);
  reply = asked();
  await page.goto("/chat");
  await reply;
  await expect(page.getByTestId("placement-banner")).toHaveCount(0);
});
