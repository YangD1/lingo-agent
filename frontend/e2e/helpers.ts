import { expect, type Page } from "@playwright/test";

export const PASSWORD = "correct horse battery";

export function uniqueEmail(prefix = "learner"): string {
  return `${prefix}-${Date.now()}-${Math.floor(Math.random() * 1e6)}@example.com`;
}

export async function register(page: Page, email: string, name = "Lee"): Promise<void> {
  await page.goto("/register");
  await page.locator("#email").fill(email);
  await page.locator("#display_name").fill(name);
  await page.locator("#password").fill(PASSWORD);
  await page.locator("form button[type=submit]").click();
  await expect(page).toHaveURL(/\/chat$/);
}
