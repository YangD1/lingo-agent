import { expect, type Locator, type Page, test } from "@playwright/test";

import { register, uniqueEmail, useFakeModel } from "./helpers";

test.use({ locale: "zh-CN" });

// The chat workspace (ADR 0043): a long text read closely or a piece of writing revised
// beside the chat. The fake model translates, analyses and proposes edits by the script in
// e2e/fake_llm.py.

const input = (page: Page) => page.getByRole("textbox", { name: /输入消息/ });
const messages = (page: Page) =>
  page.getByRole("list", { name: "消息" }).locator(':scope > li > [data-slot="message"]');
const workspace = (page: Page) => page.getByTestId("workspace");

/** Send, and wait for the reply to finish (the stop button turns back into send). */
async function send(page: Page, text: string, reply: string | RegExp) {
  await input(page).fill(text);
  await input(page).press("Enter");
  await expect(messages(page).last()).toContainText(reply);
  await expect(page.getByRole("button", { name: "发送" })).toBeVisible();
}

/** Paste `text` into the input box as the browser would (the box gets it, then the event). */
async function paste(box: Locator, text: string) {
  await box.fill(text);
  await box.evaluate((element, text) => {
    const data = new DataTransfer();
    data.setData("text/plain", text);
    element.dispatchEvent(new ClipboardEvent("paste", { bubbles: true, cancelable: true, clipboardData: data }));
  }, text);
}

// Four paragraphs, over the 800 characters that make a paste "a long text".
const ARTICLE = [
  "Cities around the world are planting more trees along their busy streets. The trees give shade on hot days and make the air a little cleaner. Many people say the streets also feel calmer and friendlier than before.",
  "Planting a tree is cheap, but looking after it is not. Young trees need water every week during their first summers, and someone has to check them for damage. Some cities now ask local families to adopt a tree near their home.",
  "Scientists are still measuring how much cooler a street with trees can be. Early results show a difference of several degrees in the afternoon. The researchers hope the numbers will help other towns decide where to plant next.",
  "Not everyone is happy about the new trees. Some shop owners worry that the branches will hide their signs, and drivers complain about leaves on the road in autumn. City officials say they will listen and choose smaller trees for narrow streets.",
].join("\n\n");

// The learner's writing: two "he/she/it like" mistakes for the fake model to fix.
const ESSAY =
  "My family lives in a small house near the river. She like music every day and plays the piano after school. He like green tea after lunch with his friends. We are happy there.";

test("a pasted article is read closely: translation, sentence analysis, a quote to the tutor, kept on reload and on a phone", async ({
  page,
}) => {
  await register(page, uniqueEmail());
  await useFakeModel(page);
  await page.goto("/chat");

  // A long paste offers the workspace; reading it there takes it out of the input box.
  await paste(input(page), ARTICLE);
  const hint = page.getByTestId("paste-hint");
  await expect(hint).toContainText("这是一段长文");
  await hint.getByRole("button", { name: "在工作区精读" }).click();
  await expect(workspace(page)).toBeVisible();
  await expect(input(page)).toHaveValue("");
  await expect(page).toHaveURL(/[?&]w=[0-9a-f-]{36}/);
  const text = page.getByTestId("workspace-text");
  await expect(text).toContainText("Cities around the world");
  await expect(workspace(page)).toContainText("Cities around the world are planting");

  // In the original, one paragraph's translation under it on request.
  await page.getByTestId("paragraph-translate").first().click();
  await expect(page.getByTestId("translation")).toHaveText("译文 Cities around the world are planting");
  await page.screenshot({ path: test.info().outputPath("workspace-reading-paragraph.png") });

  // Side by side with a translation, paragraph by paragraph (the first one kept).
  await page.getByRole("radio", { name: "对照" }).click();
  await expect(page.getByTestId("paragraph-translate")).toHaveCount(0);
  await expect(page.getByTestId("translation").first()).toHaveText("译文 Cities around the world are planting");
  await expect(page.getByTestId("translation")).toHaveCount(4);

  // Sentence analysis: tap a sentence, read it under it, tap again to close.
  await page.getByTestId("reading-analyse").click();
  const sentence = text.locator("[data-sentence='1']").first();
  await expect(sentence).toHaveText(/The trees give shade/);
  await sentence.click();
  const analysis = page.getByTestId("sentence-analysis");
  await expect(analysis).toContainText("句意 The trees give shade on hot days");
  await expect(analysis).toContainText("The trees give");
  await sentence.click();
  await expect(analysis).toHaveCount(0);
  await page.getByTestId("reading-analyse").click();

  // Select a passage, "ask the tutor": it goes in as a quote, and the document reaches the model.
  await text.locator("p", { hasText: "Planting a tree is cheap" }).first().evaluate((p) => {
    const range = document.createRange();
    range.selectNodeContents(p);
    const selection = window.getSelection();
    selection?.removeAllRanges();
    selection?.addRange(range);
    p.dispatchEvent(new MouseEvent("mouseup", { bubbles: true }));
  });
  await page.getByTestId("ask-about-selection").click();
  await expect(input(page)).toHaveValue(/^> Planting a tree is cheap/);
  await input(page).press("End");
  await input(page).pressSequentially("What does adopt mean here?");
  await input(page).press("Enter");
  await expect(messages(page).nth(1)).toContainText("In your document:");
  await expect(messages(page).nth(1)).toContainText("What does adopt mean here?");
  await expect(messages(page).first()).toContainText("> Planting a tree is cheap");
  await page.screenshot({ path: test.info().outputPath("workspace-reading-desktop.png") });

  // A reload keeps the document open (`?w=`), with the translation kept.
  await page.reload();
  await expect(workspace(page)).toBeVisible();
  await expect(page.getByTestId("workspace-text")).toContainText("Cities around the world");

  // Between tablet and desktop: the workspace covers the chat.
  await page.setViewportSize({ width: 900, height: 800 });
  await expect(workspace(page)).toBeVisible();
  await page.screenshot({ path: test.info().outputPath("workspace-reading-tablet.png") });

  // On a phone: chat and workspace are two tabs.
  await page.setViewportSize({ width: 390, height: 844 });
  const tabs = page.getByRole("radiogroup", { name: "对话或工作区" });
  await expect(tabs).toBeVisible();
  await expect(workspace(page)).toBeVisible();
  await page.screenshot({ path: test.info().outputPath("workspace-reading-phone.png") });
  await tabs.getByRole("radio", { name: "对话" }).click();
  await expect(workspace(page)).toBeHidden();
  await expect(messages(page).nth(1)).toContainText("In your document:");
  await tabs.getByRole("radio", { name: "工作区" }).click();
  await expect(workspace(page)).toBeVisible();
});

test("the tutor opens the learner's writing, proposes edits; one accepted, one declined, then reverted", async ({
  page,
}) => {
  await register(page, uniqueEmail());
  await useFakeModel(page);
  await page.goto("/chat");

  // Asked to, the tutor opens the text just sent as a writing document, beside the chat.
  await send(page, ESSAY, "You said:");
  await send(page, "Please open it in the workspace as my writing.", "suggestion on a card");
  await expect(page.getByText(/在工作区打开了《/)).toBeVisible();
  await expect(workspace(page)).toBeVisible();
  await expect(page).toHaveURL(/[?&]w=[0-9a-f-]{36}/);
  const editor = page.getByTestId("writing-editor");
  await expect(editor).toHaveValue(ESSAY);
  await expect(page.getByTestId("workspace-version")).toHaveText("第 1 版");

  // Asked to improve it, the tutor proposes two changes; nothing changes until decided.
  await send(page, "Can you improve it?", "suggestion on a card");
  await expect(page.getByText(/对《My family lives.*》提了 2 处修改/)).toBeVisible();
  const items = page.getByTestId("edit-item");
  await expect(items).toHaveCount(2);
  await expect(editor).toHaveValue(ESSAY);
  await page.screenshot({ path: test.info().outputPath("workspace-writing-edits.png") });

  // Accept the first, decline the second.
  await items.filter({ hasText: "She like" }).getByTestId("edit-accept").click();
  await expect(editor).toHaveValue(/She likes music every day/);
  await expect(items).toHaveCount(1);
  await items.getByTestId("edit-decline").click();
  await expect(page.getByTestId("workspace-edits")).toHaveCount(0);
  await expect(editor).toHaveValue(/He like green tea/);
  await expect(page.getByTestId("workspace-version")).toHaveText("第 2 版");

  // Back to the first version: a new version with the old text.
  await page.getByTestId("writing-versions-toggle").click();
  const first = page.getByTestId("writing-version").filter({ hasText: "第 1 版" });
  await first.getByRole("button", { name: "查看" }).click();
  await expect(page.getByTestId("writing-version-text")).toHaveText(ESSAY);
  await page.getByTestId("writing-revert").click();
  await expect(editor).toHaveValue(ESSAY);
  await expect(page.getByTestId("workspace-version")).toHaveText("第 3 版");
  await expect(page.getByTestId("writing-versions")).toHaveCount(0); // closes once done
  await page.getByTestId("writing-versions-toggle").click();
  await expect(page.getByTestId("writing-version").filter({ hasText: "第 3 版" })).toContainText("回到第 1 版");

  // On a phone the writing view's toolbar still fits.
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByTestId("writing-review-button")).toBeInViewport();
  await page.screenshot({ path: test.info().outputPath("workspace-writing-phone.png") });
});
