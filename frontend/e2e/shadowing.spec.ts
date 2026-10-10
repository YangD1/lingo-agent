import { expect, type Page, test } from "@playwright/test";

import { FAKE_LLM_URL, register, uniqueEmail, useFakeModel } from "./helpers";

// Shadowing (ADR 0028 §5, task 57): the real recorder (AudioWorklet → 16 kHz WAV) on
// Chromium's fake microphone, scored by e2e/fake_llm.py standing in for Azure, or only
// compared with its transcript when no assessment is set up.
test.use({
  locale: "zh-CN",
  launchOptions: {
    args: ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"],
  },
});

const SENTENCE = "You said: I went home.";
const messages = (page: Page) =>
  page.getByRole("list", { name: "消息" }).locator(':scope > li > [data-slot="message"]');

async function route(page: Page, section: string, model: string) {
  const response = await page.request.put(`/api/tenant/routes/${section}/default`, {
    data: { models: [model] },
  });
  expect(response.status()).toBe(200);
}

/** Pronunciation assessment by the fake Azure (its base_url is the fake server itself). */
async function useFakeAssessment(page: Page) {
  const connection = await page.request.post("/api/tenant/connections", {
    data: {
      name: "speech",
      kind: "azure_speech",
      base_url: FAKE_LLM_URL.replace(/\/v1$/, ""),
      api_key: "fake-azure-key",
    },
  });
  expect(connection.status()).toBe(201);
  await route(page, "pronunciation", "speech:pronunciation");
}

/** Chats once and opens shadowing on the reply, on the sentence that echoes the message. */
async function shadowReply(page: Page) {
  const input = page.getByRole("textbox", { name: /输入消息/ });
  await input.fill("I went home.");
  await input.press("Enter");
  await expect(messages(page).nth(1)).toContainText(SENTENCE);
  await page.getByTestId("shadowing-open").click();
  const panel = page.getByTestId("shadowing-panel");
  await panel.getByRole("button", { name: SENTENCE }).click();
  await expect(panel.getByTestId("shadowing-sentence")).toHaveText(SENTENCE);
  return panel;
}

/** Records a few seconds: the fake microphone beeps now and then, a short take can miss it. */
async function readBack(page: Page) {
  const panel = page.getByTestId("shadowing-panel");
  const scored = page.waitForResponse(
    (r) => r.url().endsWith("/api/speech/shadowing") && r.request().method() === "POST",
  );
  await panel.getByRole("button", { name: "开始录音" }).click();
  await expect(panel.getByText("3 / 30 秒")).toBeVisible({ timeout: 10_000 });
  await panel.getByRole("button", { name: "读完了" }).click();
  const response = await scored;
  expect(response.status()).toBe(201);
  return response;
}

test("shadowing a tutor reply is assessed word by word, kept in the history and deletable", async ({
  page,
}) => {
  await register(page, uniqueEmail());
  await useFakeModel(page);
  await useFakeAssessment(page);
  await page.reload();

  const panel = await shadowReply(page);
  await expect(panel.getByTestId("ai-badge-shadowing")).toBeVisible();
  const response = await readBack(page);
  // The backend took the recording, so the browser sent what Azure takes: it refuses
  // anything but 16 kHz mono 16-bit WAV of at most 30 seconds (422 invalid_audio).
  expect((await response.json()).audio_seconds).toBeGreaterThanOrEqual(3);

  const result = panel.getByTestId("shadowing-result");
  await expect(result).toHaveAttribute("data-mode", "assessment");
  await expect(panel.getByTestId("shadowing-overall")).toHaveText("84");
  const went = panel.getByTestId("shadowing-words").getByRole("button", { name: "went" });
  await expect(went).toHaveAttribute("data-grade", "poor");
  await went.click();
  await expect(panel.getByTestId("shadowing-word-detail")).toContainText("准确度 40");
  await expect(panel.getByTestId("shadowing-word-detail")).toContainText("/ɛ/ 20");

  const off = panel.getByTestId("shadowing-mispronounced");
  await expect(off).toContainText("went");
  await off.getByRole("button", { name: "加入生词本" }).click();
  await expect(off).toContainText("已加入");

  await page.goto("/learner");
  const history = page.getByTestId("learner-shadowing");
  const item = history.getByTestId("shadowing-item");
  await expect(item).toHaveCount(1);
  await expect(item).toContainText("84");
  await expect(item).toContainText(SENTENCE);
  await expect(item).toContainText("读不准：went");
  await item.getByRole("button", { name: "删除这条记录" }).click();
  await item.getByRole("button", { name: "删除", exact: true }).click();
  await expect(history).toContainText("还没有跟读记录");
});

test("without pronunciation assessment, shadowing compares a transcript and says it's rough", async ({
  page,
}) => {
  await register(page, uniqueEmail());
  await useFakeModel(page);
  await route(page, "asr", "fake:fake-whisper");
  await page.reload();

  const panel = await shadowReply(page);
  await expect(panel.getByTestId("ai-badge-shadowing_rough")).toBeVisible();
  await readBack(page);

  // The fake transcript is "I goed home yesterday.": "went" was heard as "goed".
  await expect(panel.getByTestId("shadowing-result")).toHaveAttribute("data-mode", "rough");
  await expect(panel.getByTestId("shadowing-rough")).toContainText("粗略结果");
  await expect(panel.getByTestId("shadowing-scores")).toHaveCount(0);
  const went = panel.getByTestId("shadowing-words").getByRole("button", { name: "went" });
  await expect(went).toHaveAttribute("data-grade", "poor");
  await went.click();
  await expect(panel.getByTestId("shadowing-word-detail")).toContainText("听成了 “goed”");
});
