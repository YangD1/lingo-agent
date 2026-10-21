import { expect, test } from "@playwright/test";

test.use({ locale: "zh-CN" });

// A broken font path or a missing public/ in the standalone build still renders the
// page (in the system fonts), so only a real browser notices (ADR 0059).
test("text is set in LXGW WenKai, loading only the pieces the page uses", async ({ page }) => {
  const pieces: string[] = [];
  page.on("response", (response) => {
    const path = new URL(response.url()).pathname;
    if (path.startsWith("/fonts/wenkai/") && response.ok()) pieces.push(path.split("/").pop()!);
  });

  await page.goto("/login");
  await expect(page.getByRole("button", { name: "登录" })).toBeVisible();
  expect(await page.evaluate(() => getComputedStyle(document.body).fontFamily)).toMatch(/^"LXGW WenKai"/);

  await page.evaluate(() => document.fonts.ready);
  await expect
    .poll(() => pieces)
    .toEqual(expect.arrayContaining(["regular-latin.woff2", "regular-ui.woff2"]));
  // The rarely used pieces stay on the server.
  expect(pieces).not.toContain("regular-symbols.woff2");
  expect(pieces.length).toBeLessThan(10);
});
