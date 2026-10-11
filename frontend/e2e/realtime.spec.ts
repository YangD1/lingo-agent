import { expect, type Page, test } from "@playwright/test";

import { FAKE_LLM_URL, register, uniqueEmail, useFakeModel } from "./helpers";

// Realtime calls (ADR 0030, task 62) on Chromium's fake microphone, through the
// production build's /api proxy (the WebSocket upgrade included, Q62j). e2e/fake_llm.py
// plays the vendor: the tutor opens, the learner's first 1.5 s of audio is a question
// about "serendipity", which the tutor looks up and adds, then it suggests hanging up.
test.use({
  locale: "zh-CN",
  launchOptions: {
    args: ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"],
  },
});

const WORD = "serendipity";
// A summary is only made for a call of 30 seconds or more (Q61g).
const SUMMARY_SECONDS = 31;

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

test("a realtime call: subtitles, the tutor's tools, hanging up, transcript and summary", async ({
  page,
}) => {
  test.setTimeout(120_000); // the call lasts SUMMARY_SECONDS
  await register(page, uniqueEmail());
  await useFakeModel(page);
  await useFakeRealtime(page);

  // Each card offers a call next to push-to-talk practice (Q62a).
  await page.goto("/speaking");
  await expect(page.getByTestId("speaking-call-minutes")).toContainText("今天还剩 30 分钟");
  await page.getByTestId("speaking-call-self_intro").click();
  await expect(page).toHaveURL(/\/speaking\/call\?scenario=self_intro$/);
  await expect(page.getByRole("heading", { name: "自我介绍" })).toBeVisible();

  const call = page.getByTestId("realtime-call");
  await page.getByTestId("call-connect").click();
  const connected = Date.now();
  await expect(call).toHaveAttribute("data-phase", "live");
  await expect(page.getByTestId("call-time-left")).toHaveText(/^1[45]:\d\d$/);

  // The tutor speaks first; the microphone's audio is heard as the learner's question.
  await expect(call.getByText("Hi! What would you like to talk about?")).toBeVisible();
  await expect(call.getByText(`Can you explain ${WORD}? Please add it to my words.`)).toBeVisible();
  const tools = call.getByTestId("call-tool");
  await expect(tools.filter({ hasText: `私教查了 ${WORD}` })).toBeVisible();
  const added = tools.filter({ hasText: `已把 ${WORD} 加入生词本` });
  await expect(added).toBeVisible();
  await expect(call.getByText(/It means finding good things by chance/)).toBeVisible();

  // Taken off the word list again, right there (Q62e).
  await added.getByRole("button", { name: "撤销" }).click();
  await expect(call.getByText("已从生词本移除")).toBeVisible();

  // The tutor may only suggest hanging up; the learner keeps talking (Q61c).
  const suggestion = page.getByTestId("call-end-suggested");
  await expect(suggestion).toBeVisible();
  await suggestion.getByRole("button", { name: "继续聊" }).click();
  await expect(suggestion).toBeHidden();
  await expect(call.getByText("Great talking with you. Bye for now!")).toBeVisible();

  await page.waitForTimeout(Math.max(0, SUMMARY_SECONDS * 1000 - (Date.now() - connected)));
  await page.getByTestId("call-hang-up").click();

  // On to the call's page (Q62b): the summary once made in the background, the transcript
  // and what the tutor did.
  await expect(page).toHaveURL(/\/speaking\/[\w-]+\?call_end=hangup$/);
  const summary = page.getByTestId("speaking-summary");
  await expect(summary).toHaveAttribute("data-status", "done", { timeout: 20_000 });
  await expect(summary).toContainText("通话");
  await expect(page.getByTestId("speaking-intelligibility")).toBeVisible();
  const transcript = page.getByTestId("call-transcript");
  await expect(transcript).toContainText("Hi! What would you like to talk about?");
  await expect(transcript).toContainText(`Can you explain ${WORD}?`);
  await expect(transcript).toContainText("Great talking with you. Bye for now!");
  const activity = transcript.getByRole("button", { name: /^私教做了什么：.*查了 1 个词/ });
  await expect(activity).toBeVisible({ timeout: 20_000 });
  await activity.click();
  await expect(transcript.getByText("私教建议结束通话")).toBeVisible();
  // The word taken off during the call shows as such.
  await expect(transcript.getByText("已移出")).toBeVisible();

  // The call is in the history, and is not offered as a practice to go on with.
  await page.goto("/speaking");
  const row = page.getByTestId("speaking-session").first();
  await expect(row).toContainText("通话");
  await expect(page.getByTestId("speaking-continue")).toBeHidden();
});

test("without a realtime connection there is no call, and the call page says why", async ({
  page,
}) => {
  await register(page, uniqueEmail());
  await useFakeModel(page);

  await page.goto("/speaking");
  await expect(page.getByTestId("speaking-scenario-free")).toBeVisible();
  await expect(page.getByTestId("speaking-call-free")).toBeHidden();
  await expect(page.getByTestId("speaking-call-minutes")).toBeHidden();

  // Reached anyway (an old link): the backend refuses and the page explains.
  await page.goto("/speaking/call");
  await page.getByTestId("call-connect").click();
  const refused = page.getByTestId("call-not-connected");
  await expect(refused).toContainText("还没配置实时语音模型");
  await expect(refused.getByRole("link", { name: "去设置" })).toHaveAttribute("href", "/settings");
});
