import { expect, type Page, test } from "@playwright/test";

import { register, uniqueEmail, useFakeModel } from "./helpers";

// Speaking practice (ADR 0029, task 59) on Chromium's fake microphone: voice turns are
// transcribed by e2e/fake_llm.py as "I goed home yesterday.", each said to last 150
// seconds, so two of them make the daily plan's 5 minutes of the learner talking.
test.use({
  locale: "zh-CN",
  launchOptions: {
    args: ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"],
  },
});

const HEARD = "I goed home yesterday.";
const FIXED = "I went home yesterday.";
const messages = (page: Page) =>
  page.getByRole("list", { name: "消息" }).locator(':scope > li > [data-slot="message"]');

/** One voice turn: tap to start, tap again to send (Q59a). */
async function talk(page: Page) {
  const mic = page.getByTestId("speaking-mic");
  await mic.click();
  await expect(mic).toHaveAttribute("data-recording", "true");
  // The fake microphone beeps now and then; a short take can miss it and be refused as silent.
  await page.waitForTimeout(3_000);
  await mic.click();
}

test("a speaking practice: voice turns, fixing a transcript, the summary and today's plan", async ({
  page,
}) => {
  await register(page, uniqueEmail());
  await useFakeModel(page);
  const asr = await page.request.put("/api/tenant/routes/asr/default", {
    data: { models: ["fake:fake-whisper"] },
  });
  expect(asr.status()).toBe(200);

  // The draft never has speaking; the learner switches it on (Q59d).
  await page.goto("/dashboard");
  const plan = page.getByTestId("today-plan");
  await expect(plan).toHaveAttribute("data-status", "proposed");
  const row = plan.getByTestId("plan-row-speaking");
  await expect(row).toContainText("今天自己说满 5 分钟就算完成");
  await row.getByRole("switch").click();
  await expect(plan.getByTestId("plan-total")).toHaveText("预计 28 分钟");
  await plan.getByRole("button", { name: "确认计划" }).click();
  const item = plan.getByTestId("plan-item-speaking");
  await expect(item.getByTestId("plan-progress")).toHaveText("0/5 分钟");
  await item.getByRole("link", { name: "去说" }).click();

  await expect(page).toHaveURL(/\/speaking$/);
  await page.getByTestId("speaking-scenario-self_intro").click();
  await expect(page).toHaveURL(/\/speaking\/[\w-]+$/);
  await expect(page.getByRole("heading", { name: "自我介绍" })).toBeVisible();
  // The tutor speaks first (Q58e).
  await expect(messages(page).nth(0)).toContainText("What's your name?");

  // Spoken and sent without a confirm step (Q59b); the transcript was off, so fix it (Q59c).
  await talk(page);
  await expect(messages(page).nth(1)).toHaveText(HEARD);
  await expect(messages(page).nth(2)).toContainText(`You said: ${HEARD}`);
  await page.getByTestId("speaking-fix").click();
  await page.getByRole("textbox", { name: "你说的话" }).fill(FIXED);
  await page.getByRole("button", { name: "发送改好的" }).click();
  await expect(messages(page).nth(3)).toHaveText(FIXED);
  await expect(messages(page).nth(4)).toContainText(`You said: ${FIXED}`);
  await expect(page.getByText("已改", { exact: true })).toBeVisible();

  await talk(page);
  await expect(messages(page).nth(5)).toHaveText(HEARD);
  await expect(messages(page).nth(6)).toContainText(`You said: ${HEARD}`);

  await page.getByTestId("speaking-end").click();
  const summary = page.getByTestId("speaking-summary");
  await expect(summary).toHaveAttribute("data-status", "done");
  await expect(summary).toContainText("说了 5 分钟");
  await expect(page.getByTestId("speaking-intelligibility")).toHaveText("基本能懂");
  await expect(page.getByTestId("summary-went-well")).toContainText("完整的句子");
  const mistakes = page.getByTestId("summary-mistakes");
  await expect(mistakes).toContainText("I goed home");
  await expect(mistakes).toContainText("I went home");
  await expect(page.getByTestId("summary-more-natural")).toContainText("I got home yesterday.");
  await expect(page.getByTestId("summary-next")).toContainText("Nice to meet you.");

  // Five minutes of the learner's own voice: the plan's speaking is done.
  await page.goto("/dashboard");
  await expect(item).toHaveAttribute("data-complete", "true");
  await expect(item.getByTestId("plan-progress")).toHaveText("5/5 分钟");

  await page.goto("/speaking");
  await expect(page.getByTestId("speaking-session")).toContainText("说了 5 分钟");
});
