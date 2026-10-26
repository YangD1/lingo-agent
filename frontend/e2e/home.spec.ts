import { expect, test } from "@playwright/test";

// The logged-out home page (ADR 0065). Signed out: a signed-in visit to / goes on to the dashboard.
test.use({ locale: "en-US" });

test("first screen: heading, links, word wall and lens", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1, name: "Your AI English assistant" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Create an account" }).first()).toHaveAttribute("href", "/register");
  await expect(page.getByRole("link", { name: "Sign up" })).toHaveAttribute("href", "/register");
  await expect(page.getByRole("link", { name: "Log in" }).first()).toHaveAttribute("href", "/login");

  await expect(page.getByTestId("word-wall")).toBeAttached();
  await expect(page.getByTestId("lens")).toHaveAttribute("data-ready", "");
  await expect(page.getByTestId("lens-caption")).not.toBeEmpty();
});

test("the chat demo builds near the viewport and its tabs switch scenes", async ({ page }) => {
  await page.goto("/");
  const demo = page.locator("#more");
  await demo.scrollIntoViewIfNeeded();
  await expect(page.getByTestId("demo-window")).toHaveAttribute("data-built", "true");
  await expect(page.getByTestId("demo-window")).not.toBeEmpty();

  const tabs = demo.getByRole("group", { name: /./ }).getByRole("button");
  await expect(tabs).toHaveCount(5);
  await expect(tabs.first()).toHaveAttribute("aria-pressed", "true");
  const live = demo.locator("[aria-live]");
  await expect(live).toHaveText("Memory & fixes");

  await tabs.nth(2).click();
  await expect(tabs.nth(2)).toHaveAttribute("aria-pressed", "true");
  await expect(tabs.first()).toHaveAttribute("aria-pressed", "false");
  await expect(live).toHaveText("Close reading");
});

test("with reduced motion everything below the fold is shown at once", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/");
  await page.getByRole("heading", { name: "Start with one conversation." }).scrollIntoViewIfNeeded();
  await expect(page.getByTestId("demo-window")).toHaveAttribute("data-built", "true");
  // cards do not fade in: every one is fully opaque without waiting for an intersection
  const hidden = await page.locator("[data-rise]").evaluateAll(
    (els) => els.filter((e) => getComputedStyle(e).opacity !== "1").length,
  );
  expect(hidden).toBe(0);
});

test("the footer links out and the page never scrolls sideways", async ({ page }) => {
  await page.goto("/");
  const footer = page.getByRole("contentinfo");
  await expect(footer.getByRole("link", { name: "GitHub" })).toHaveAttribute("href", /github\.com/);
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 844 });
    await page.mouse.wheel(0, 20_000);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow, `width ${width}`).toBeLessThanOrEqual(0);
  }
});

test.describe("on a phone", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("the language button moves to the footer", async ({ page }) => {
    await page.goto("/");
    const buttons = page.getByRole("button", { name: "切换到简体中文" });
    await expect(buttons).toHaveCount(1);
    await expect(page.getByRole("contentinfo").getByRole("button", { name: "切换到简体中文" })).toBeVisible();
    await buttons.click();
    await expect(page.locator("html")).toHaveAttribute("lang", "zh-CN");
    await expect(page.getByRole("heading", { level: 1, name: "你的 AI 英语助手" })).toBeVisible();
    // the chat demo is rebuilt in the new language too
    await page.locator("#more").scrollIntoViewIfNeeded();
    await expect(page.getByRole("button", { name: "记忆和纠错" })).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByTestId("demo-window")).toHaveAttribute("data-built", "true");
  });
});
