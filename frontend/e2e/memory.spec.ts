import { expect, type Page, test } from "@playwright/test";

import { register, uniqueEmail, useFakeModel } from "./helpers";

test.use({ locale: "zh-CN" });

// The fake model remembers what follows "remember that", and answers "what do you
// remember" with the facts it finds in its system prompt (e2e/fake_llm.py).
const FACT = "My cat is called Mochi.";

const input = (page: Page) => page.getByRole("textbox", { name: /输入消息/ });
const messages = (page: Page) => page.getByRole("list", { name: "消息" }).locator(":scope > li");
const facts = (page: Page) => page.getByRole("list", { name: "私教记住的事" }).locator("li");

/**
 * Send and wait until the turn is over: `reply` must match the complete reply, and the send
 * button only comes back after the final event. Leaving mid-stream would cancel the turn,
 * and with it reflection.
 */
async function send(page: Page, text: string, reply: string | RegExp) {
  await input(page).fill(text);
  await input(page).press("Enter");
  await expect(messages(page).last()).toHaveText(reply);
  await expect(page.getByRole("button", { name: "发送" })).toBeVisible();
}

/** Ask in a new conversation, so the answer depends on memory rather than chat history. */
async function askInNewConversation(page: Page): Promise<string> {
  await page.goto("/chat");
  await page.getByRole("button", { name: "新对话" }).click();
  // Streamed word by word: only the complete reply ends in "." or "nothing yet".
  await send(page, "What do you remember?", /^I remember: (.+\.|nothing yet)$/);
  return (await messages(page).nth(1).textContent()) ?? "";
}

test("chat → memory appears → delete it → a new conversation no longer uses it", async ({
  page,
}) => {
  await register(page, uniqueEmail());
  await useFakeModel(page);

  await send(
    page,
    "Please remember that my cat is called Mochi.",
    "Nice try! You said: Please remember that my cat is called Mochi.",
  );

  // Reflection runs in the background after the reply.
  await expect(async () => {
    await page.goto("/memory");
    await expect(facts(page)).toHaveCount(1, { timeout: 1000 });
  }).toPass();
  await expect(facts(page).first()).toContainText(FACT);
  await expect(facts(page).first().getByRole("link")).toHaveText(/^来自“/);

  expect(await askInNewConversation(page)).toContain("Mochi");

  // Starting that conversation summarised the first one.
  await page.goto("/memory");
  const summaries = page.getByRole("list", { name: "会话摘要" }).locator("li");
  await expect(summaries.first()).toContainText("The learner practised small talk.");

  page.once("dialog", (dialog) => dialog.accept());
  await facts(page).first().getByRole("button", { name: "删除" }).click();
  await expect(page.getByText("还没有。你在聊天中提到关于自己的信息时")).toBeVisible();
  await page.reload();
  await expect(facts(page)).toHaveCount(0);

  const answer = await askInNewConversation(page);
  expect(answer).toContain("nothing yet");
  expect(answer).not.toContain("Mochi");
});

test("the learner edits, adds and clears what the tutor remembers", async ({ page }) => {
  await register(page, uniqueEmail());
  await page.goto("/memory");

  // Profile: only what is saved here is kept, and it survives a reload.
  const profile = page.getByTestId("profile");
  await expect(profile.getByTestId("profile-cefr")).toContainText("尚未评估");
  await profile.getByLabel("职业").fill("护士");
  await profile.getByLabel("目标考试").selectOption("ielts");
  await profile.getByLabel("兴趣").fill("旅行，电影、travel");
  await profile.getByRole("button", { name: "保存画像" }).click();
  await expect(profile.getByRole("status")).toHaveText("画像已保存。");
  await expect(profile.getByRole("button", { name: "保存画像" })).toBeDisabled();
  await page.reload();
  await expect(profile.getByLabel("职业")).toHaveValue("护士");
  await expect(profile.getByLabel("目标考试")).toHaveValue("ielts");
  await expect(profile.getByLabel("兴趣")).toHaveValue("旅行, 电影, travel");

  // Facts: add two, edit one, then forget them all.
  const add = page.getByRole("textbox", { name: "告诉私教一件要记住的事" });
  await add.fill("I have a job interview in late October.");
  await page.getByRole("button", { name: "记住这条" }).click();
  await expect(facts(page)).toHaveCount(1);
  await add.fill("I like jazz.");
  await page.getByRole("button", { name: "记住这条" }).click();
  await expect(facts(page)).toHaveCount(2);
  await expect(facts(page).nth(0)).toContainText("I like jazz."); // newest first
  await expect(facts(page).nth(1)).toContainText("I have a job interview in late October.");

  await facts(page).nth(1).getByRole("button", { name: "编辑" }).click();
  await page.getByRole("textbox", { name: "编辑记忆" }).fill("The interview is on 28 October.");
  await page.getByRole("button", { name: "保存", exact: true }).click();
  await expect(facts(page).first()).toContainText("The interview is on 28 October.");

  await page.reload();
  await expect(facts(page)).toHaveCount(2);
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "忘掉全部事实" }).click();
  await expect(facts(page)).toHaveCount(0);
  await page.reload();
  await expect(facts(page)).toHaveCount(0);
});
