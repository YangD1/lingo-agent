import path from "node:path";

import { expect, test } from "@playwright/test";

import { register, uniqueEmail, useFakeModel } from "./helpers";

// voice.wav is a second of silence; Chromium loops it as the microphone. Launch options
// force their own worker, so this lives apart from attachments.spec.ts.
test.use({
  locale: "zh-CN",
  launchOptions: {
    args: [
      "--use-fake-ui-for-media-stream",
      "--use-fake-device-for-media-stream",
      `--use-file-for-fake-audio-capture=${path.join(__dirname, "fixtures", "voice.wav")}`,
    ],
  },
});

test("a recording without sound is not uploaded", async ({ page }) => {
  await register(page, uniqueEmail());
  await useFakeModel(page);

  await page.getByRole("button", { name: "录制语音消息" }).click();
  await expect(page.getByText(/0:01 \/ 3:00/)).toBeVisible();
  await page.getByRole("button", { name: "停止录音" }).click();

  await expect(page.getByRole("alert").filter({ hasText: "没录到声音" })).toBeVisible();
  await expect(page.getByRole("list", { name: "附件" })).toHaveCount(0);
});
