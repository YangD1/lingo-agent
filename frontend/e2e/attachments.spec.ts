import { readFileSync } from "node:fs";
import path from "node:path";

import { expect, type Locator, type Page, test } from "@playwright/test";

import { register, uniqueEmail, useFakeModel } from "./helpers";

// A fake microphone, so recording runs the real MediaRecorder without a permission prompt.
test.use({
  locale: "zh-CN",
  launchOptions: {
    args: ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"],
  },
});

const fixture = (name: string) => path.join(__dirname, "fixtures", name);
// What e2e/fake_llm.py reads in every image and hears in every recording.
const IMAGE_TEXT = "I goed to the park yesterday.";
const TRANSCRIPT = "I goed home yesterday.";

const input = (page: Page) => page.getByRole("textbox", { name: /输入消息/ });
const messages = (page: Page) => page.getByRole("list", { name: "消息" }).locator(':scope > li > [data-slot="message"]');
const tray = (page: Page) => page.getByRole("list", { name: "附件" }).locator(":scope > li");
const sendButton = (page: Page) => page.getByRole("button", { name: "发送", exact: true });

const attach = (page: Page, ...names: string[]) =>
  page.getByTestId("attachment-input").setInputFiles(names.map(fixture));

/** Route images and speech to the fake model too (vision and asr have no automatic fallback). */
async function setUpAttachmentModels(page: Page) {
  for (const [route, model] of [
    ["llm/vision", "fake:fake-tutor"],
    ["asr/default", "fake:fake-whisper"],
  ]) {
    const response = await page.request.put(`/api/tenant/routes/${route}`, {
      data: { models: [model] },
    });
    expect(response.status()).toBe(200);
  }
}

/** Dispatch a paste or drop of a fixture file, as the browser would. */
async function dispatchFile(target: Locator, kind: "paste" | "drop", name: string, type: string) {
  const base64 = readFileSync(fixture(name)).toString("base64");
  await target.evaluate(
    (element, { kind, name, type, base64 }) => {
      const bytes = Uint8Array.from(atob(base64), (c) => c.charCodeAt(0));
      const data = new DataTransfer();
      data.items.add(new File([bytes], name, { type }));
      const init = { bubbles: true, cancelable: true };
      if (kind === "paste") {
        element.dispatchEvent(new ClipboardEvent("paste", { ...init, clipboardData: data }));
      } else {
        element.dispatchEvent(new DragEvent("dragover", { ...init, dataTransfer: data }));
        element.dispatchEvent(new DragEvent("drop", { ...init, dataTransfer: data }));
      }
    },
    { kind, name, type, base64 },
  );
}

test("an image needs a vision model: the card says so and links to settings", async ({ page }) => {
  await register(page, uniqueEmail());
  await useFakeModel(page); // chat only

  await attach(page, "worksheet.png");

  const card = tray(page).first();
  await expect(card).toHaveAttribute("data-status", "failed");
  await expect(card).toContainText("还没有配置能看图的模型");
  await expect(card.getByRole("link", { name: "去设置" })).toHaveAttribute("href", "/settings");
  await input(page).fill("What does it say?");
  await expect(sendButton(page)).toBeDisabled();
  await expect(page.getByText("附件处理完成（或移除）后才能发送。")).toBeVisible();

  await card.getByRole("button", { name: "移除 worksheet.png" }).click();
  await expect(tray(page)).toHaveCount(0);
  await expect(sendButton(page)).toBeEnabled();
});

test("an image is read, corrected, sent with the turn and kept in history", async ({ page }) => {
  await register(page, uniqueEmail());
  await useFakeModel(page);
  await setUpAttachmentModels(page);

  await attach(page, "worksheet.png");
  const card = tray(page).first();
  await expect(card).toContainText("已识别");
  await card.getByRole("button", { name: "查看或修改 worksheet.png 的识别结果" }).click();
  const reading = page.getByRole("textbox", { name: "导师将看到的 worksheet.png 内容" });
  await expect(reading).toHaveValue(new RegExp(IMAGE_TEXT.replace(/\./g, "\\.")));
  await reading.fill("Text in the image:\nI goed to the zoo.");
  await page.getByRole("button", { name: "保存", exact: true }).click();
  await expect(reading).toHaveCount(0);

  await input(page).fill("What is wrong here?");
  await input(page).press("Enter");

  const reply = messages(page).nth(1);
  // The vision route answered, saw the picture, and got the corrected reading.
  await expect(reply).toContainText("I can see 1 image(s).");
  await expect(reply).toContainText("I goed to the zoo.");
  await expect(tray(page)).toHaveCount(0);

  await page.reload();
  const image = messages(page).nth(0).getByRole("img");
  await expect(image).toBeVisible();
  // Loaded through the authenticated content endpoint.
  expect(await image.evaluate((img: HTMLImageElement) => img.naturalWidth)).toBeGreaterThan(0);
  await expect(messages(page).nth(0)).toContainText("What is wrong here?");
});

test("documents, including a scanned PDF, are read and sent as text", async ({ page }) => {
  await register(page, uniqueEmail());
  await useFakeModel(page);
  await setUpAttachmentModels(page);

  await attach(page, "essay.txt", "scanned.pdf");
  await expect(tray(page)).toHaveCount(2);
  await expect(tray(page).nth(0)).toContainText("已提取文字");
  await expect(tray(page).nth(1)).toContainText("已提取文字");

  await sendButton(page).click(); // no text: the documents are the message

  const reply = messages(page).nth(1);
  await expect(reply).toContainText("I goed to the park and eated ice cream."); // essay.txt
  await expect(reply).toContainText(IMAGE_TEXT); // the scanned page, read by the vision model
  await expect(reply).not.toContainText("I can see"); // documents go as text, not images
  await expect(messages(page).nth(0).getByRole("link", { name: /essay\.txt/ })).toHaveAttribute(
    "download",
    "essay.txt",
  );
});

test("a voice message can be sent without typing; its corrected transcript is the text", async ({
  page,
}) => {
  await register(page, uniqueEmail());
  await useFakeModel(page);
  await setUpAttachmentModels(page);

  await attach(page, "voice.wav");
  const card = tray(page).first();
  await expect(card).toContainText("已转写");
  await card.getByRole("button", { name: "查看或修改 voice.wav 的识别结果" }).click();
  const transcript = page.getByRole("textbox", { name: "voice.wav 的转写" });
  await expect(transcript).toHaveValue(TRANSCRIPT);
  await transcript.fill("I went home yesterday.");
  await page.getByRole("button", { name: "保存", exact: true }).click();

  await sendButton(page).click();

  await expect(messages(page).nth(0)).toContainText("I went home yesterday.");
  await expect(messages(page).nth(0).locator("audio")).toHaveCount(1);
  await expect(messages(page).nth(1)).toContainText("You said: I went home yesterday.");
  await page.reload();
  await expect(messages(page).nth(0)).toContainText("I went home yesterday.");
  await expect(messages(page).nth(0).locator("audio")).toHaveCount(1);
});

test("recording with the microphone produces a transcribed voice attachment", async ({ page }) => {
  await register(page, uniqueEmail());
  await useFakeModel(page);
  await setUpAttachmentModels(page);

  await page.getByRole("button", { name: "录制语音消息" }).click();
  await expect(page.getByRole("status").filter({ hasText: "正在录音" })).toBeVisible();
  await expect(page.getByText(/0:01 \/ 3:00/)).toBeVisible();
  await page.getByRole("button", { name: "停止录音" }).click();

  const card = tray(page).first();
  await expect(card).toContainText(/voice-.*\.(webm|m4a|ogg)/);
  await expect(card).toContainText("已转写");
});

test("pasted and dropped files are attached; big photos are shrunk to JPEG first", async ({
  page,
}) => {
  await register(page, uniqueEmail());
  await useFakeModel(page);
  await setUpAttachmentModels(page);

  const upload = page.waitForResponse(
    (r) => r.request().method() === "POST" && r.url().endsWith("/attachments"),
  );
  await dispatchFile(input(page), "paste", "big-photo.png", "image/png");
  // The backend keeps the name it was sent: .jpg means the browser re-encoded the photo.
  // (Playwright can't show a multipart body built from a Blob, so check the result.)
  expect((await (await upload).json()).filename).toBe("big-photo.jpg");
  await expect(tray(page).first()).toContainText("已识别");

  await dispatchFile(page.getByText(/用英语随便说点什么/), "drop", "essay.txt", "text/plain");
  await expect(tray(page)).toHaveCount(2);
  await expect(tray(page).nth(1)).toContainText("已提取文字");
});
