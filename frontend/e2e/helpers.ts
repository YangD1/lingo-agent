import { readFileSync } from "node:fs";
import path from "node:path";

import { expect, type Page } from "@playwright/test";

export const FAKE_LLM_URL = `http://127.0.0.1:${process.env.E2E_LLM_PORT ?? 8101}/v1`;

export const PASSWORD = "correct horse battery";

export function uniqueEmail(prefix = "learner"): string {
  return `${prefix}-${Date.now()}-${Math.floor(Math.random() * 1e6)}@example.com`;
}

/** Registers and lands on the dashboard (the home page), then opens chat, where most specs start. */
export async function register(page: Page, email: string, name = "Lee"): Promise<void> {
  await page.goto("/register");
  await page.locator("#email").fill(email);
  await page.locator("#display_name").fill(name);
  await page.locator("#password").fill(PASSWORD);
  await page.locator("form button[type=submit]").click();
  await expect(page).toHaveURL(/\/dashboard$/);
  await page.goto("/chat");
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

// Answering "no" to exactly the made-up words keeps the placement test's vocabulary
// result reliable and high, so the sample book's words are offered for marking known.
export const PSEUDOWORDS = new Set(
  readFileSync(
    path.join(__dirname, "../../backend/app/adaptive/placement/pseudowords.txt"),
    "utf8",
  )
    .split("\n")
    .filter((line) => line && !line.startsWith("#")),
);

export const placementProgress = (page: Page) => page.getByTestId("placement-progress");

/** Answer the current placement question and wait for the next one (or the result). */
export async function answerOne(page: Page): Promise<void> {
  const progress = placementProgress(page);
  const before = await progress.textContent();
  // Vocabulary counts read "第 n / 40 题", grammar ones "第 n 题（最多 20 题）".
  if (before?.includes("/")) {
    const word = await page.locator("[data-testid=placement-question] p[lang=en]").textContent();
    await page.keyboard.press(PSEUDOWORDS.has(word ?? "") ? "n" : "y");
  } else {
    await page.keyboard.press("1");
  }
  await expect(async () => {
    const done = await page.getByTestId("placement-result").isVisible();
    expect(done || (await progress.textContent()) !== before).toBe(true);
  }).toPass();
}

/**
 * Answer the item on screen with the fake model's key (e2e/fake_llm.py), or, for a
 * translation when `wrongTranslation` is set, with a wrong sentence that the grading
 * model marks. Returns the item's format.
 */
export async function answerPractice(page: Page, wrongTranslation: boolean): Promise<string> {
  const item = page.getByTestId("practice-item");
  const format = (await item.getAttribute("data-format")) ?? "";
  switch (format) {
    case "choice4":
      await item.getByRole("button", { name: /works$/ }).click();
      break;
    case "cloze":
      await item.getByRole("textbox").fill("drinks");
      await item.getByRole("textbox").press("Enter");
      break;
    case "find_fix":
      await item.getByRole("button", { name: "第 2 段：go" }).click();
      await item.getByRole("textbox", { name: "改成" }).fill("goes");
      await item.getByRole("textbox", { name: "改成" }).press("Enter");
      break;
    case "transform":
      await item.getByRole("textbox").fill("My sister plays tennis.");
      await item.getByRole("textbox").press("Enter");
      break;
    case "translate":
      await item.getByRole("textbox").fill(wrongTranslation ? "She walk to work." : "She walks to work.");
      await item.getByRole("textbox").press("Enter");
      break;
    case "rewrite_own":
      await item.getByRole("textbox").fill("She likes music.");
      await item.getByRole("textbox").press("Enter");
      break;
    default:
      throw new Error(`unexpected format ${format}`);
  }
  await expect(page.getByTestId("practice-verdict")).toBeVisible();
  return format;
}
