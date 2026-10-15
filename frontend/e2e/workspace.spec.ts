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

// A Markdown article (task 84): headings, a list, bold, a link, a table, code and a quote.
const MARKDOWN = [
  "# Street trees",
  "Cities around the world are planting more trees along their **busy streets**. The trees give shade on hot days and make the air a little [cleaner](https://example.com). Many people say the streets also feel calmer than before.",
  "## What a tree needs",
  "- Water every week during its first summers\n- Someone to check it for damage\n- A family nearby to adopt it",
  "| City | Trees planted |\n| --- | --- |\n| Paris | 100 |\n| Milan | 80 |",
  "```\nplant(tree, street)\n```",
  "> Planting a tree is cheap, but looking after it is not.",
  "Not everyone is happy about the new trees. Some shop owners worry that the branches will hide their signs, and drivers complain about leaves on the road in autumn.",
  "Scientists are still measuring how much cooler a street with trees can be. Early results show a difference of several degrees in the afternoon, and the researchers hope the numbers will help other towns decide where to plant next.",
].join("\n\n");

test("a pasted Markdown article reads as Markdown: headings, lists, bold, tables and code kept", async ({ page }) => {
  await register(page, uniqueEmail());
  await useFakeModel(page);
  await page.goto("/chat");

  await paste(input(page), MARKDOWN);
  await page.getByTestId("paste-hint").getByRole("button", { name: "在工作区精读" }).click();
  const text = page.getByTestId("workspace-text");
  await expect(text.getByRole("heading", { level: 1, name: "Street trees" })).toBeVisible();
  await expect(text.getByRole("heading", { level: 2, name: "What a tree needs" })).toBeVisible();
  await expect(text.getByRole("listitem")).toHaveCount(3);
  await expect(text.locator("strong", { hasText: "busy streets" })).toBeVisible();
  await expect(text.getByRole("link", { name: "cleaner" })).toHaveAttribute("href", "https://example.com");
  await expect(text.getByRole("table")).toContainText("Milan");
  await expect(text.locator("pre")).toHaveText("plant(tree, street)");
  await expect(text).not.toContainText("**");
  // Every block but the code can be translated.
  await expect(page.getByTestId("paragraph-translate")).toHaveCount(8);

  // The list's translation sits under the list.
  const list = text.locator("[data-paragraph]").filter({ has: page.getByRole("list") });
  await list.getByTestId("paragraph-translate").click();
  await expect(list.getByTestId("translation")).toContainText("译文");

  // Side by side, the code is shown once and never translated.
  await page.getByRole("radio", { name: "对照" }).click();
  await expect(page.getByTestId("translation").first()).toBeVisible();
  await text.getByText("Not everyone is happy").scrollIntoViewIfNeeded(); // translated as they come into view
  await expect(page.getByTestId("translation")).toHaveCount(8);
  await expect(text.locator("pre")).toHaveCount(1);
  await page.screenshot({ path: test.info().outputPath("workspace-markdown-side.png") });
  await page.getByRole("radio", { name: "原文" }).click();

  // Sentence analysis keeps the headings and the list items, without the marks.
  await page.getByTestId("reading-analyse").click();
  await expect(text.getByRole("heading", { level: 2, name: "What a tree needs" })).toBeVisible();
  await expect(text.locator('[data-unit="item"]')).toHaveCount(3);
  const sentence = text.locator("[data-sentence]", { hasText: "Cities around the world are planting more trees" });
  await expect(sentence).toHaveText(/along their busy streets\./);
  await sentence.click();
  await expect(page.getByTestId("sentence-analysis")).toContainText("Cities around the");
  await page.screenshot({ path: test.info().outputPath("workspace-markdown-analyse.png") });
});

// The same kind of article copied from a web page (task 85): the clipboard's HTML, with the
// page's menu, a picture and a script around it, goes into the input box as Markdown.
const PAGE_HTML = `<meta charset="utf-8"><!--StartFragment-->
<nav><a href="/">Home</a> <a href="/news">News</a></nav>
<h1>Street trees</h1>
<p>${ARTICLE.split("\n\n")[0].replace("busy streets", "<strong>busy streets</strong>").replace("cleaner", '<a href="https://example.com">cleaner</a>')}</p>
<img src="https://example.com/tree.jpg" alt="A tree">
<h2>What a tree needs</h2>
<ul><li>Water every week during its first summers</li><li>Someone to check it for damage</li><li>A family nearby to adopt it</li></ul>
<table><tbody><tr><td><p>City</p></td><td><p>Trees planted</p></td></tr><tr><td><p>Paris</p></td><td><p>100</p></td></tr><tr><td><p>Milan</p></td><td><p>80</p></td></tr></tbody></table>
<script>document.title = "pwned"</script>
${ARTICLE.split("\n\n").slice(1).map((p) => `<p>${p}</p>`).join("\n")}
<!--EndFragment-->`;

test("an article copied from a web page pastes as Markdown and reads with its structure", async ({ page }) => {
  await register(page, uniqueEmail());
  await useFakeModel(page);
  await page.goto("/chat");

  const box = input(page);
  await box.focus();
  await box.evaluate((element, html) => {
    const data = new DataTransfer();
    data.setData("text/html", html);
    data.setData("text/plain", "Street trees\nCities around the world...");
    element.dispatchEvent(new ClipboardEvent("paste", { bubbles: true, cancelable: true, clipboardData: data }));
  }, PAGE_HTML);
  await expect(box).toHaveValue(/^# Street trees\n\nCities around the world .*\*\*busy streets\*\*/);
  await expect(box).toHaveValue(/\[cleaner\]\(https:\/\/example\.com\)/);
  await expect(box).not.toHaveValue(/<|Home|pwned|tree\.jpg/);

  // The browser's undo takes the whole paste back out.
  await box.press("ControlOrMeta+z");
  await expect(box).toHaveValue("");
  await box.press("ControlOrMeta+Shift+z");
  await expect(box).toHaveValue(/^# Street trees/);

  await page.getByTestId("paste-hint").getByRole("button", { name: "在工作区精读" }).click();
  const text = page.getByTestId("workspace-text");
  await expect(text.getByRole("heading", { level: 1, name: "Street trees" })).toBeVisible();
  await expect(text.getByRole("heading", { level: 2, name: "What a tree needs" })).toBeVisible();
  await expect(text.getByRole("listitem")).toHaveCount(3);
  await expect(text.locator("strong", { hasText: "busy streets" })).toBeVisible();
  await expect(text.getByRole("link", { name: "cleaner" })).toHaveAttribute("href", "https://example.com");
  await expect(text.getByRole("columnheader", { name: "Trees planted" })).toBeVisible();
  await expect(text.getByRole("table")).toContainText("Milan");
  await expect(text).not.toContainText("Home");
  await expect(page).not.toHaveTitle("pwned");
  await page.screenshot({ path: test.info().outputPath("workspace-html-paste.png") });
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

test("the tutor opens the workspace by itself, closes it when told, and stops when told (ADR 0045)", async ({
  page,
}) => {
  await register(page, uniqueEmail());
  await useFakeModel(page);
  await page.goto("/chat");
  const asking = `Can you help me understand this?\n\n${ARTICLE}`;

  // A long text to understand: the tutor opens it for reading without being asked to.
  await send(page, asking, "suggestion on a card");
  await expect(page.getByText(/在工作区打开了《/)).toBeVisible();
  await expect(workspace(page)).toBeVisible();
  await expect(page).toHaveURL(/[?&]w=[0-9a-f-]{36}/);

  // "Close it": the panel closes, the document stays and opens again from the card.
  await send(page, "Please close the workspace.", "suggestion on a card");
  await expect(workspace(page)).toBeHidden();
  await expect(page).not.toHaveURL(/[?&]w=/);
  const closed = page.locator('[data-testid="tutor-card"][data-kind="workspace_closed"]');
  await expect(closed).toContainText("收起了工作区，文档都还在");
  await closed.getByRole("button", { name: "重新打开" }).click();
  await expect(workspace(page)).toBeVisible();
  await page.getByRole("button", { name: "关闭工作区" }).click();
  await expect(workspace(page)).toBeHidden();

  // "Don't open it by yourself": applied at once, undoable, and the next long text stays in the chat.
  await send(page, "From now on, don't open the workspace by itself.", "suggestion on a card");
  const auto = page.locator('[data-testid="tutor-card"][data-kind="workspace_auto"]');
  await expect(auto).toContainText("以后只在你要求时才打开工作区");
  await expect(auto).toHaveAttribute("data-status", "applied");
  await send(page, asking, "word0");
  await expect(workspace(page)).toBeHidden();
  await expect(page.locator('[data-testid="tutor-card"][data-kind="workspace"]')).toHaveCount(1);

  // The assistant settings show it off.
  await page.goto("/tutor");
  await expect(page.locator("#tutor-workspace-auto")).not.toBeChecked();
});
