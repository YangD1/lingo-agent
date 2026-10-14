import { execFileSync } from "node:child_process";
import path from "node:path";

import { expect, type Page, test } from "@playwright/test";

import { FAKE_LLM_URL, PASSWORD, useFakeModel } from "./helpers";

// README screenshots (task 72.2), only run by `make screenshots`: the demo account's real,
// engine-made history (`make demo-seed`, task 72.3); only what a model would write on the
// spot (chat replies, the call) comes from e2e/fake_llm.py. 1280×800, overwrites
// docs/screenshots/<page>-<zh|en>.png.

const OUT = path.join(__dirname, "../../docs/screenshots");
const DEMO = "demo@lingo.example.com";

test.use({
  viewport: { width: 1280, height: 800 },
  launchOptions: {
    args: ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"],
  },
});

const LOCALES = [
  { lang: "zh", locale: "zh-CN" },
  { lang: "en", locale: "en-US" },
] as const;

function seed(lang: string) {
  execFileSync("uv", ["run", "--project", "../backend", "python", "e2e/demo_seed.py", PASSWORD, lang], {
    stdio: "inherit",
  });
}

async function useFakeRealtime(page: Page) {
  const connection = await page.request.post("/api/tenant/connections", {
    data: {
      name: "voice",
      kind: "openai_compatible",
      base_url: FAKE_LLM_URL,
      api_key: "sk-fake",
      params: {
        realtime_url: `${FAKE_LLM_URL.replace(/^http/, "ws")}/realtime`,
        realtime_dialect: "ga",
      },
    },
  });
  expect(connection.status()).toBe(201);
  const route = await page.request.put("/api/tenant/routes/realtime/default", {
    data: { models: ["voice:fake-realtime"] },
  });
  expect(route.status()).toBe(200);
}

async function shoot(page: Page, name: string, lang: string) {
  // Fonts, avatars and charts settle before the picture is taken.
  await page.evaluate(() => document.fonts.ready);
  await page.waitForLoadState("networkidle");
  await page.mouse.move(0, 0); // no hover card left open from the last click
  await page.waitForTimeout(500);
  await page.screenshot({ path: path.join(OUT, `${name}-${lang}.png`) });
}

/** Opens the first record linked from a list page (/writing → /writing/<id>). */
async function openFirst(page: Page, list: string) {
  await page.goto(list);
  const record = page.locator(`a[href^="${list}/"]:not([href*="/call"])`).first();
  await expect(record).toBeVisible();
  await record.click();
  await expect(page).toHaveURL(new RegExp(`${list}/[\\w-]+$`));
}

for (const { lang, locale } of LOCALES) {
  test.describe(lang, () => {
    test.use({ locale });

    test(`home (${lang})`, async ({ page }) => {
      // Signed out: a signed-in visit to / goes on to the dashboard.
      // Reduced motion shows the chat demo's finished turn instead of a random frame.
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
      await useFakeRealtime(page);

      await page.goto("/dashboard");
      await shoot(page, "dashboard", lang);

      await page.goto("/learner");
      await shoot(page, "learner", lang);

      // Flashcards over the vocabulary page (ADR 0038), a card turned over.
      await page.goto("/vocab?review=all");
      const deck = page.getByTestId("review-deck");
      await deck.locator('h2[lang="en"]').waitFor();
      await page.keyboard.press("Space");
      await deck.getByTestId("review-back").waitFor();
      await shoot(page, "vocab", lang);

      await page.goto("/practice");
      await shoot(page, "practice", lang);

      await openFirst(page, "/writing");
      await shoot(page, "writing", lang);

      // The demo's own article (run_backend's E2E feed articles are newer and filler).
      await page.goto("/reading");
      await page.getByRole("link", { name: /Volunteers plant a million trees/ }).first().click();
      await expect(page).toHaveURL(/\/reading\/\d+$/);
      await shoot(page, "reading", lang);

      await openFirst(page, "/speaking");
      await shoot(page, "speaking", lang);

      await page.goto("/tutor");
      await shoot(page, "tutor", lang);

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

      // A call: the fake vendor's script looks up and adds "serendipity".
      await page.goto("/speaking/call?scenario=self_intro");
      await page.getByTestId("call-connect").click();
      const call = page.getByTestId("realtime-call");
      await expect(call.getByTestId("call-tool").nth(1)).toBeVisible({ timeout: 20_000 });
      await expect(call.getByText(/It means finding good things by chance/)).toBeVisible();
      await shoot(page, "call", lang);
      await page.getByTestId("call-hang-up").click();
    });
  });
}
