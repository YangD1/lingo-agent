import { expect, type Page } from "@playwright/test";

export const FAKE_LLM_URL = `http://127.0.0.1:${process.env.E2E_LLM_PORT ?? 8101}/v1`;

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

/**
 * Add the fake model through the API (the settings UI is tested separately). Its default model
 * is enough for chat: no route needed (ADR 0007 §3).
 */
export async function useFakeModel(page: Page): Promise<void> {
  const connection = await page.request.post("/api/tenant/connections", {
    data: {
      name: "fake",
      kind: "openai_compatible",
      base_url: FAKE_LLM_URL,
      api_key: "sk-fake",
      default_model: "fake-tutor",
    },
  });
  expect(connection.status()).toBe(201);
}
