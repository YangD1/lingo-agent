import { expect, type Page, test } from "@playwright/test";

import { register, uniqueEmail } from "./helpers";

test.use({ locale: "zh-CN" });

/** Font files the page fetched, as "<choice>/<file>". */
function recordFonts(page: Page): string[] {
  const files: string[] = [];
  page.on("response", (response) => {
    const path = new URL(response.url()).pathname;
    if (path.startsWith("/fonts/") && path.endsWith(".woff2") && response.ok()) {
      files.push(path.slice("/fonts/".length));
    }
  });
  return files;
}

async function bodyFont(page: Page): Promise<string> {
  return page.evaluate(() => getComputedStyle(document.body).fontFamily);
}

// A broken font path or a missing public/ in the standalone build still renders the
// page (in the system fonts), so only a real browser notices (ADR 0059, 0060).
test("the default font is Inter + Noto Sans SC, loading only the pieces the page uses", async ({
  page,
}) => {
  const files = recordFonts(page);

  await page.goto("/login");
  await expect(page.getByRole("button", { name: "登录" })).toBeVisible();
  expect(await bodyFont(page)).toMatch(/^Inter, "Noto Sans SC"/);

  await page.evaluate(() => document.fonts.ready);
  await expect
    .poll(() => files)
    .toEqual(expect.arrayContaining(["sans/inter-latin.woff2", "sans/notosanssc-ui.woff2"]));
  expect(files.every((f) => f.startsWith("sans/"))).toBe(true);
  expect(files.length).toBeLessThan(10);
});

test("a font picked in settings applies at once and from the first paint after a reload", async ({
  page,
}) => {
  await register(page, uniqueEmail());
  await page.goto("/settings#display");
  await page.getByRole("radio", { name: /霞鹜文楷/ }).check();
  expect(await bodyFont(page)).toMatch(/^"LXGW WenKai"/);

  const files = recordFonts(page);
  await page.goto("/dashboard");
  // The boot script set it before React: no default font in between.
  expect(await page.evaluate(() => document.documentElement.dataset.font)).toBe("wenkai");
  expect(await bodyFont(page)).toMatch(/^"LXGW WenKai"/);
  await page.evaluate(() => document.fonts.ready);
  await expect.poll(() => files).toContain("wenkai/regular-ui.woff2");
  expect(files.filter((f) => !f.startsWith("wenkai/"))).toEqual([]);
});
