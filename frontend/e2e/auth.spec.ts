import { expect, test } from "@playwright/test";

import { PASSWORD, register, uniqueEmail } from "./helpers";

test.use({ locale: "zh-CN" });

test("register, log out, and log back in to the page you asked for", async ({ page }) => {
  const email = uniqueEmail();

  await page.goto("/settings");
  await expect(page).toHaveURL(/\/login\?next=%2Fsettings$/);

  await register(page, email, "小李");
  // The chat page starts with the sidebar as an icon rail: the account menu sits behind the avatar.
  await page.getByRole("button", { name: "账户" }).click();
  await expect(page.getByTestId("current-user")).toHaveText("小李");

  await page.getByRole("button", { name: "退出登录" }).click();
  await expect(page).toHaveURL(/\/login$/);
  await page.goto("/chat");
  await expect(page).toHaveURL(/\/login\?next=%2Fchat$/);

  await page.goto("/login?next=%2Fsettings");
  await page.locator("#email").fill(email);
  await page.locator("#password").fill("wrong password");
  await page.getByRole("button", { name: "登录" }).click();
  await expect(page.locator("form").getByRole("alert")).toHaveText("邮箱或密码不正确。");

  await page.locator("#password").fill(PASSWORD);
  await page.getByRole("button", { name: "登录" }).click();
  await expect(page).toHaveURL(/\/settings$/);
});

test("registering a taken email shows a localized error", async ({ page, browser }) => {
  const email = uniqueEmail();
  await register(page, email);

  const other = await browser.newPage({ locale: "zh-CN" });
  await other.goto("/register");
  await other.locator("#email").fill(email);
  await other.locator("#password").fill(PASSWORD);
  await other.locator("form button[type=submit]").click();
  await expect(other.locator("form").getByRole("alert")).toHaveText("这个邮箱已经注册过了。");
  await other.close();
});

test("a token the backend rejects does not cause a redirect loop", async ({ page, context }) => {
  // Unexpired but badly signed: the proxy lets it through, the backend says 401.
  const encode = (value: object) => Buffer.from(JSON.stringify(value)).toString("base64url");
  const token = `${encode({ alg: "HS256" })}.${encode({ sub: "x", exp: Date.now() / 1000 + 3600 })}.bad`;
  await context.addCookies([{ name: "lingo_access_token", value: token, url: "http://localhost:3100" }]);

  await page.goto("/chat");

  await expect(page).toHaveURL(/\/login$/);
  const cookies = await context.cookies();
  expect(cookies.find((c) => c.name === "lingo_access_token")).toBeUndefined();
});
