import { execFileSync } from "node:child_process";
import path from "node:path";

import { expect, type Page, test } from "@playwright/test";

import { PASSWORD, useFakeModel } from "./helpers";

// README screenshots (task 72.2), only run by `make screenshots`: the demo account's real,
// engine-made history (`make demo-seed`, task 72.3); only what a model would write on the
// spot (chat replies) comes from e2e/fake_llm.py. 1280×800, overwrites
// docs/screenshots/<page>-<zh|en>.png. Only what the README shows (task 128): the home page
// on its own row, then chat, learner model, reading and vocabulary.

const OUT = path.join(__dirname, "../../docs/screenshots");
const DEMO = "demo@lingo.example.com";

test.use({ viewport: { width: 1280, height: 800 } });

const LOCALES = [
  { lang: "zh", locale: "zh-CN" },
  { lang: "en", locale: "en-US" },
] as const;

function seed(lang: string) {
  execFileSync("uv", ["run", "--project", "../backend", "python", "e2e/demo_seed.py", PASSWORD, lang], {
    stdio: "inherit",
  });
}

async function shoot(page: Page, name: string, lang: string) {
  // Fonts, avatars and charts settle before the picture is taken.
  await page.evaluate(() => document.fonts.ready);
  await page.waitForLoadState("networkidle");
  await page.mouse.move(0, 0); // no hover card left open from the last click
  await page.waitForTimeout(500);
  await page.screenshot({ path: path.join(OUT, `${name}-${lang}.png`) });
}

for (const { lang, locale } of LOCALES) {
  test.describe(lang, () => {
    test.use({ locale });

    test(`home (${lang})`, async ({ page }) => {
      // Signed out: a signed-in visit to / goes on to the dashboard.
      // Reduced motion builds each chat demo turn at once and skips the cards' fade-in.
      await page.emulateMedia({ reducedMotion: "reduce" });
      await page.goto("/");
      await shoot(page, "home", lang);
    });

    test(`demo account pages (${lang})`, async ({ page }) => {
      test.setTimeout(180_000);
      seed(lang);
      const login = await page.request.post("/api/auth/login", {
        data: { email: DEMO, password: PASSWORD },
      });
      expect(login.status()).toBe(200);
      await useFakeModel(page);

      await page.goto("/learner");
      await shoot(page, "learner", lang);

      // Flashcards over the vocabulary page (ADR 0038), a card turned over.
      await page.goto("/vocab?review=all");
      const deck = page.getByTestId("review-deck");
      await deck.locator('h2[lang="en"]').waitFor();
      await page.keyboard.press("Space");
      await deck.getByTestId("review-back").waitFor();
      await shoot(page, "vocab", lang);

      // The demo's own article (run_backend's E2E feed articles are newer and filler).
      await page.goto("/reading");
      await page.getByRole("link", { name: /Volunteers plant a million trees/ }).first().click();
      await expect(page).toHaveURL(/\/reading\/\d+$/);
      await shoot(page, "reading", lang);

      // Chat: two turns on the weak point; the replies are e2e/fake_llm.py's DEMO_CHAT.
      await page.goto("/chat");
      const input = page.locator("textarea").first();
      const list = page.locator('[data-slot="message"]');
      for (const [n, text] of [
        "I have been to Hangzhou last month with my family.",
        "We walked around West Lake and I have tried the Longjing tea.",
      ].entries()) {
        await input.fill(text);
        // Enabled once the previous turn has finished streaming.
        const send = page.getByRole("button", { name: /^(发送|Send)$/ });
        await expect(send).toBeEnabled({ timeout: 15_000 });
        await send.click();
        await expect(list).toHaveCount(2 * (n + 1));
        await expect(list.nth(2 * n + 1)).not.toBeEmpty();
      }
      await expect(page).toHaveURL(/\/chat\?c=/);
      await page.waitForTimeout(1500); // the reply finishes streaming
      await shoot(page, "chat", lang);
    });
  });
}
