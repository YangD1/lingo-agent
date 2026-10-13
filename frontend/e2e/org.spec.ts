import { expect, test } from "@playwright/test";

import { register, uniqueEmail, useFakeModel } from "./helpers";

test.use({ locale: "zh-CN" });

// ADR 0031: a main account lends its model to a member, within quotas it sets.
test("invite, join, use the main account's model until the quota runs out, then your own, then leave", async ({
  page,
  browser,
}) => {
  // The main account has a model and creates a one-use invite.
  await register(page, uniqueEmail("main"), "Ada");
  await useFakeModel(page);
  await page.goto("/settings#members");
  const members = page.locator("#members");
  await expect(members).toContainText("还没有成员");
  await members.getByRole("button", { name: "创建邀请链接" }).click();
  const link = await members.getByRole("textbox", { name: "邀请链接" }).inputValue();
  expect(link).toMatch(/\/join\?code=/);
  await expect(members).toContainText("已用 0 / 1");

  // The member, in another browser, opens the link: sees what is offered, then agrees.
  const memberContext = await browser.newContext({ locale: "zh-CN" });
  const member = await memberContext.newPage();
  await register(member, uniqueEmail("member"), "Bo");
  await member.goto(link);
  await expect(member.getByText("Ada 给你的额度：")).toBeVisible();
  await expect(member.getByRole("table", { name: "提供的额度" })).toContainText("200,000");
  await member.getByRole("button", { name: "加入 Ada" }).click();
  await expect(member).toHaveURL(/\/settings#membership$/);
  await expect(member.locator("#membership")).toContainText("使用 Ada 提供的模型");
  await expect(member.getByTestId("route-source-chat")).toHaveText("由 Ada 提供：你自己没有配这项的模型。");

  // Chat runs on the main account's model, and the badge says whose quota it uses.
  await member.goto("/chat");
  await member.getByTestId("ai-badge-chat_message").hover();
  await expect(member.getByTestId("ai-badge-details")).toContainText("由 Ada 提供：扣对方分给你的额度。");
  const input = member.getByRole("textbox", { name: /输入消息/ });
  await input.fill("I goed home");
  await input.press("Enter");
  await expect(member.getByText("Nice try! You said: I goed home")).toBeVisible();
  await member.screenshot({ path: test.info().outputPath("member-chat.png") });

  // The main account sees the member's use (never the chat itself) and lowers the cap.
  const row = page.getByTestId("member-row");
  await expect(async () => {
    await page.reload();
    await expect(row.getByRole("table", { name: "Bo 的用量" }).locator("tbody tr").first()).not.toContainText(
      "0 / 200,000",
      { timeout: 2_000 },
    );
  }).toPass({ timeout: 20_000 });
  await expect(members).not.toContainText("I goed home");
  await row.getByRole("button", { name: "调整额度" }).click();
  await row.getByLabel("对话与文本 · 每日上限").fill("10");
  await row.getByRole("button", { name: "保存" }).click();
  await expect(row.getByRole("table", { name: "Bo 的用量" }).locator("tbody tr").first()).toContainText("/ 10");
  // Its usage card shows the member's calls apart from its own.
  await page.getByRole("radio", { name: "按成员" }).click();
  const byMember = page.getByRole("table", { name: "按成员" });
  await expect(byMember.getByRole("row", { name: /^Bo/ })).toBeVisible();
  await page.screenshot({ path: test.info().outputPath("main-members.png"), fullPage: true });

  // The member's quota is used up: chat says so, and so does settings.
  await input.fill("I has a cat");
  await input.press("Enter");
  await expect(member.getByRole("alert").filter({ hasText: "主账号给你的额度暂时用完了" })).toBeVisible();
  await member.goto("/settings");
  await expect(member.getByTestId("route-chat")).toContainText("Ada 给你的这项额度暂时用完了");

  // With a connection of their own, the member's calls go there, not to the quota.
  await useFakeModel(member);
  await member.reload();
  await expect(member.getByTestId("route-source-chat")).toHaveText(
    "自动：按添加连接的先后，使用各连接的默认模型。",
  );
  await member.goto("/chat");
  await member.getByTestId("ai-badge-chat_message").hover();
  await expect(member.getByTestId("ai-badge-details")).not.toContainText("由 Ada 提供");
  await input.fill("I has a dog");
  await input.press("Enter");
  await expect(member.getByText("Nice try! You said: I has a dog")).toBeVisible();

  // The member leaves; the main account lists them as gone.
  await member.goto("/settings#membership");
  const membership = member.locator("#membership");
  await membership.getByRole("button", { name: "退出" }).click();
  await membership.getByRole("group", { name: "不再使用 Ada 提供的模型？" }).getByRole("button", { name: "退出" }).click();
  await expect(membership.getByLabel("邀请码")).toBeVisible();
  await page.reload();
  await expect(members).toContainText("还没有成员");
  await expect(members).toContainText("1 位已离开的成员");

  await memberContext.close();
});
