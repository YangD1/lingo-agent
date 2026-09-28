import { expect, test } from "@playwright/test";

const TAGLINE = {
  en: "Your AI English tutor.",
  zh: "你的 AI 英语私教",
};

test.describe("with a Chinese browser", () => {
  test.use({ locale: "zh-CN" });

  test("follows Accept-Language, then remembers an explicit switch", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator("html")).toHaveAttribute("lang", "zh-CN");
    await expect(page.getByText(TAGLINE.zh)).toBeVisible();

    await page.getByLabel("语言").selectOption("en");
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
