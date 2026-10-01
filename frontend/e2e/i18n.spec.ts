import { expect, test } from "@playwright/test";

import { register, uniqueEmail, useFakeModel } from "./helpers";

const TAGLINE = {
  en: "Your AI English tutor",
  zh: "你的 AI 英语私教",
};

test.describe("with a Chinese browser", () => {
  test.use({ locale: "zh-CN" });

  test("follows Accept-Language, then remembers an explicit switch", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator("html")).toHaveAttribute("lang", "zh-CN");
    await expect(page.getByText(TAGLINE.zh)).toBeVisible();

    await page.getByLabel("语言").filter({ visible: true }).selectOption("en");
    await expect(page.getByText(TAGLINE.en)).toBeVisible();
    await expect(page.locator("html")).toHaveAttribute("lang", "en");

    await page.reload();
    await expect(page.getByText(TAGLINE.en)).toBeVisible();
  });
});

test.describe("with an English browser", () => {
  test.use({ locale: "en-US" });

  test("renders English by default", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByText(TAGLINE.en)).toBeVisible();
    await expect(page).toHaveTitle("Lingo Agent");
  });
});

test.describe("inside the app", () => {
  test.use({ locale: "en-US" });

  test("switching language re-renders server and client parts and keeps the conversation", async ({
    page,
  }) => {
    await register(page, uniqueEmail());
    await useFakeModel(page);
    const input = page.getByRole("textbox", { name: /Type a message/ });
    await input.fill("hello");
    await input.press("Enter");
    await expect(page.getByRole("list", { name: "Messages" }).locator(':scope > li > [data-slot="message"]').nth(1)).toContainText(
      "You said: hello",
    );
    const url = page.url();

    await page.getByRole("button", { name: "Account" }).click();
    await page.getByLabel("Language").selectOption("zh-CN");

    await expect(page.getByRole("link", { name: "设置" })).toBeVisible(); // server layout
    await expect(page.getByRole("button", { name: "新对话" })).toBeVisible(); // client component
    await expect(page.getByRole("list", { name: "消息" }).locator(':scope > li > [data-slot="message"]')).toHaveCount(2);
    expect(page.url()).toBe(url);

    await page.getByRole("link", { name: "设置" }).click();
    await expect(page.locator('[data-slot="card-title"]', { hasText: "模型连接" })).toBeVisible();
  });
});
