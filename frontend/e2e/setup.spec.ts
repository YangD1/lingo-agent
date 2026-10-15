import { expect, type Page, test } from "@playwright/test";

// Aliased: "use…" inside a helper trips the React hooks lint rule; it is not a hook.
import { register, registerNew, uniqueEmail, useFakeModel as connectFakeModel } from "./helpers";

test.use({ locale: "zh-CN" });

/** A main account with the fake model and a one-use invite link (ADR 0031). */
async function inviteLink(page: Page): Promise<string> {
  await register(page, uniqueEmail("main"), "Ada");
  await connectFakeModel(page);
  await page.goto("/settings#members");
  const members = page.locator("#members");
  await members.getByRole("button", { name: "创建邀请链接" }).click();
  const link = await members.getByRole("textbox", { name: "邀请链接" }).inputValue();
  expect(link).toMatch(/\/join\?code=/);
  return link;
}

// ADR 0042: a new account goes through the guide before the app; steps can be skipped.
test("a new account sets up first, skipping some steps, and can open the guide again", async ({
  page,
  browser,
}) => {
  const code = new URL(await inviteLink(page)).searchParams.get("code")!;

  const context = await browser.newContext({ locale: "zh-CN" });
  const learner = await context.newPage();
  await registerNew(learner, uniqueEmail("new"), "");
  await expect(learner.getByRole("heading", { name: "先认识一下" })).toBeVisible();

  // Until finished, the app sends the learner back here.
  await learner.goto("/chat");
  await expect(learner).toHaveURL(/\/setup$/);

  // 1. Name and language.
  await learner.getByLabel("怎么称呼你").fill("Bo");
  await learner.getByRole("radio", { name: "中文" }).click();
  await learner.getByRole("button", { name: "下一步" }).click();

  // 2. The model: skipping asks first; then join the main account with its code.
  await expect(learner.getByRole("heading", { name: "接入一个对话模型" })).toBeVisible();
  await learner.getByRole("button", { name: "跳过" }).click();
  await expect(learner.getByRole("alertdialog", { name: "先不接模型？" })).toBeVisible();
  await learner.getByRole("button", { name: "回去接模型" }).click();
  await learner.getByRole("radio", { name: "我有邀请码" }).click();
  await learner.getByLabel("邀请码").fill(code);
  await learner.getByRole("button", { name: "查看" }).click();
  await learner.getByRole("button", { name: "加入 Ada" }).click();

  // 3. Goals: skipped.
  await expect(learner.getByRole("heading", { name: "你想学成什么样" })).toBeVisible();
  await expect(learner.getByTestId("setup-dot-profile")).toHaveAttribute("data-set", "true");
  await expect(learner.getByTestId("setup-dot-model")).toHaveAttribute("data-set", "true");
  await learner.getByRole("button", { name: "跳过" }).click();

  // 4. The assistant's name.
  await learner.getByLabel("名字", { exact: true }).fill("Momo");
  await learner.getByRole("button", { name: "下一步" }).click();

  // 5. The level test: later.
  await expect(learner.getByRole("heading", { name: "测一下现在的水平" })).toBeVisible();
  await learner.getByRole("button", { name: "跳过" }).click();

  // The summary: what is set, what is left and where to do it.
  const summary = learner.getByTestId("setup-summary");
  await expect(summary.locator("[data-step=goals]")).toHaveAttribute("data-set", "false");
  await expect(summary.locator("[data-step=tutor]")).toHaveAttribute("data-set", "true");
  await expect(summary.getByRole("link", { name: "以后去配置" })).toHaveCount(2);
  await learner.screenshot({ path: test.info().outputPath("setup-summary.png") });
  await learner.getByRole("button", { name: "开始学习" }).click();
  await expect(learner).toHaveURL(/\/dashboard$/);

  // Finished: not sent back, and chat works on the main account's model.
  await learner.goto("/chat");
  await expect(learner).toHaveURL(/\/chat$/);
  const input = learner.getByRole("textbox", { name: /输入消息/ });
  await input.fill("I goed home");
  await input.press("Enter");
  await expect(learner.getByText("Nice try! You said: I goed home")).toBeVisible();

  // Opened again from settings: current values and ticks, no "skip all".
  await learner.goto("/settings");
  await learner.getByTestId("settings-setup-link").getByRole("link", { name: "配置引导" }).click();
  await expect(learner).toHaveURL(/\/setup$/);
  await expect(learner.getByLabel("怎么称呼你")).toHaveValue("Bo");
  await expect(learner.getByRole("radio", { name: "中文" })).toBeChecked();
  await expect(learner.getByRole("button", { name: /全部跳过/ })).toHaveCount(0);
  await expect(learner.getByTestId("setup-dot-goals")).not.toHaveAttribute("data-set");
  await learner.getByTestId("setup-dot-model").click();
  await expect(learner.getByTestId("setup-model-ready")).toContainText("已经有可用的对话模型");
  await context.close();
});

test("skip all goes straight in; a new account's invite link opens before the guide", async ({
  page,
  browser,
}) => {
  await registerNew(page, uniqueEmail("skipper"));
  await page.getByRole("button", { name: "全部跳过，先进去看看" }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
  await page.reload();
  await expect(page).toHaveURL(/\/dashboard$/);

  // Someone signs up from an invite link: the link is honoured first, then the guide's model step.
  const main = await browser.newContext({ locale: "zh-CN" });
  const link = await inviteLink(await main.newPage());
  const context = await browser.newContext({ locale: "zh-CN" });
  const invited = await context.newPage();
  await invited.goto(link);
  await expect(invited).toHaveURL(/\/login\?next=/);
  await invited.getByRole("link", { name: "去注册" }).click();
  await expect(invited.getByRole("heading", { name: "创建账号" })).toBeVisible();
  await invited.locator("#email").fill(uniqueEmail("invited"));
  await invited.locator("#password").fill("correct horse battery");
  await invited.locator("form button[type=submit]").click();
  await expect(invited.getByText("Ada 给你的额度：")).toBeVisible();
  await invited.getByRole("button", { name: "加入 Ada" }).click();
  await expect(invited).toHaveURL(/\/setup\?step=model$/);
  await expect(invited.getByTestId("setup-model-ready")).toContainText("已经有可用的对话模型");
  await context.close();
  await main.close();
});
