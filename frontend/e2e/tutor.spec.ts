import { expect, type Page, test } from "@playwright/test";

import { register, uniqueEmail, useFakeModel } from "./helpers";

test.use({ locale: "zh-CN" });

// The learner's own tutor (ADR 0032): looks, name, model and voices on "my tutor", and the
// desk pet that shows it on every page, talks while reading, and opens a chat window.

// Server read-aloud with a made-up audio element: each sentence "plays" for a while, long
// enough to see the pet talking, and records nothing else.
async function fakeAudio(page: Page) {
  await page.addInitScript(() => {
    class FakeAudio {
      src = "";
      playbackRate = 1;
      defaultPlaybackRate = 1;
      preservesPitch = true;
      onended: (() => void) | null = null;
      onerror: (() => void) | null = null;
      paused = true;
      play() {
        const src = this.src;
        this.paused = false;
        setTimeout(() => {
          if (this.src === src && !this.paused) this.onended?.();
        }, 800);
        return Promise.resolve();
      }
      pause() {
        this.paused = true;
      }
    }
    Object.defineProperty(window, "Audio", { value: FakeAudio, configurable: true });
  });
}

async function readAloudRoute(page: Page) {
  const route = await page.request.put("/api/tenant/routes/tts/default", {
    data: { models: ["fake:fake-tts"] },
  });
  expect(route.status()).toBe(200);
}

const pet = (page: Page) => page.getByTestId("tutor-pet");
const petAvatar = (page: Page) => pet(page).locator("canvas").first();

test("pick the tutor's looks and voice; the pet shows it, moves, talks while reading, opens a chat", async ({
  page,
}) => {
  await fakeAudio(page);
  await register(page, uniqueEmail());
  await useFakeModel(page);
  await readAloudRoute(page);

  // The pet is there from the start, as the default tutor.
  await page.goto("/dashboard");
  await expect(pet(page).getByRole("button", { name: "和 JOJO 聊天" })).toBeVisible();

  // Name, outfit and voices; the preview follows before saving.
  await page.goto("/tutor");
  await page.getByLabel("名字").fill("Milo");
  await expect(page.getByTestId("tutor-preview-name")).toHaveText("Milo");
  await page.getByTestId("tutor-outfit-sporty").click();
  const voices = page.getByTestId("tutor-voices");
  await expect(voices).toContainText("fake-tts · fake");
  await voices.getByLabel("美音").fill("fable");
  await voices.getByLabel("英音").fill("fable");
  await page.getByTestId("tutor-save").click();
  await expect(page.getByRole("status").filter({ hasText: "已保存。" })).toBeVisible();
  await page.screenshot({ path: test.info().outputPath("tutor-page.png"), fullPage: true });

  // The pet is the saved tutor, on every page.
  await page.goto("/dashboard");
  const button = pet(page).getByRole("button", { name: "和 Milo 聊天" });
  await expect(button).toBeVisible();
  await expect(petAvatar(page)).toHaveAttribute("data-outfit", "sporty");
  await page.screenshot({ path: test.info().outputPath("pet-dashboard.png") });

  // Dragged across, it settles on the left edge, and stays there after a reload.
  await expect(pet(page)).toHaveAttribute("data-side", "right");
  const box = (await pet(page).boundingBox())!;
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  await page.mouse.move(200, box.y, { steps: 8 });
  await page.mouse.up();
  await expect(pet(page)).toHaveAttribute("data-side", "left");
  await expect(page.getByTestId("pet-chat")).toBeHidden(); // a drag is not a tap
  await page.reload();
  await expect(pet(page)).toHaveAttribute("data-side", "left");

  // Collapsed to a small button, and back.
  await pet(page).hover();
  await pet(page).getByRole("button", { name: "收起桌宠" }).click();
  await expect(pet(page)).toHaveAttribute("data-collapsed", "true");
  await pet(page).getByRole("button", { name: "展开桌宠 Milo" }).click();
  await expect(pet(page)).not.toHaveAttribute("data-collapsed");

  // The pet talks while a reply is read aloud, in the picked voice.
  await page.goto("/chat");
  const input = page.getByRole("textbox", { name: /输入消息/ });
  await input.fill("apples");
  await input.press("Enter");
  const reply = page.locator('li[data-role="assistant"]').last();
  await expect(reply.locator('[data-slot="message"]')).toContainText("You said: apples");
  await reply.getByRole("button", { name: "朗读", exact: true }).click();
  await expect(petAvatar(page)).toHaveAttribute("data-state", "speaking");
  await expect(petAvatar(page)).not.toHaveAttribute("data-state", "speaking", { timeout: 10_000 });
  const audio = await page.request.post("/api/speech/tts", {
    data: { text: "You said: apples", language: "en-US", speed: 1 },
  });
  expect(await audio.text()).toBe("mp3:fable:You said: apples");

  // On the chat page, a tap puts the cursor in the input box; elsewhere it opens a window
  // on today's conversation, which the tutor opens the first time (ADR 0041).
  await input.blur();
  await pet(page).getByRole("button", { name: "Milo：在输入框里打字" }).click();
  await expect(input).toBeFocused();
  await page.goto("/vocab");
  await button.click();
  const window = page.getByTestId("pet-chat");
  await expect(window).toBeVisible();
  await expect(window).toContainText("of the last 7 days");
  await expect(window.locator('li[data-status="streaming"]')).toHaveCount(0);
  const small = window.getByRole("textbox", { name: /输入消息/ });
  await expect(small).toBeFocused();
  await small.fill("I goed home");
  await small.press("Enter");
  await expect(window.getByText("Nice try! You said: I goed home")).toBeVisible();
  await page.screenshot({ path: test.info().outputPath("pet-chat.png") });
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("pet-chat")).toBeHidden();
  await button.click();
  await page.getByTestId("pet-chat-open-in-chat").click();
  await expect(page).toHaveURL(/\/chat\?c=/);
  await expect(page.getByTestId("pet-chat")).toBeHidden();
  await expect(page.locator('li[data-role="assistant"]').last()).toContainText("I goed home");

  // Back to the defaults: the pet is JOJO again.
  await page.goto("/tutor");
  await page.getByTestId("tutor-reset").click();
  await page.getByRole("alertdialog").getByRole("button", { name: "恢复默认" }).click();
  await expect(page.getByRole("status").filter({ hasText: "已恢复默认。" })).toBeVisible();
  await expect(page.getByLabel("名字")).toHaveValue("");
  await expect(pet(page).getByRole("button", { name: "和 JOJO 聊天" })).toBeVisible();
  await expect(petAvatar(page)).toHaveAttribute("data-outfit", "cat");

  // Turned off, the pet is gone from every page.
  await page.getByRole("switch", { name: /^桌宠/ }).click();
  await page.getByTestId("tutor-save").click();
  await expect(page.getByRole("status").filter({ hasText: "已保存。" })).toBeVisible();
  await expect(pet(page)).toBeHidden();
  await page.goto("/dashboard");
  await expect(page.getByRole("heading").first()).toBeVisible();
  await expect(pet(page)).toBeHidden();
});

// ADR 0032 §2 with ADR 0031: a member picks among the models the main account lends them.
test("a member picks the chat model from the main account's chain, and nothing else", async ({
  page,
  browser,
}) => {
  await register(page, uniqueEmail("main"), "Ada");
  await useFakeModel(page);
  const route = await page.request.put("/api/tenant/routes/llm/chat", {
    data: { models: ["fake:fake-tutor", "fake:fake-alt"] },
  });
  expect(route.status()).toBe(200);
  const invite = await page.request.post("/api/org/invites", { data: {} });
  expect(invite.status()).toBe(201);
  const { code } = await invite.json();

  const memberContext = await browser.newContext({ locale: "zh-CN" });
  const member = await memberContext.newPage();
  await register(member, uniqueEmail("member"), "Bo");
  await member.goto(`/join?code=${code}`);
  await member.getByRole("button", { name: "加入 Ada" }).click();
  await expect(member).toHaveURL(/\/settings#membership$/);

  // Only the main account's chain is offered, and the page says whose it is.
  await member.goto("/tutor");
  const card = member.getByTestId("tutor-chat");
  await expect(card.getByTestId("tutor-provided-by")).toHaveText(
    "由 Ada 提供：用的是对方的连接，扣对方分给你的额度。",
  );
  const select = card.getByLabel("模型");
  await select.click();
  await expect(member.getByRole("option")).toHaveText([
    "跟随设置页（现在：fake-tutor · fake）",
    "fake-tutor · fake",
    "fake-alt · fake",
  ]);
  await member.getByRole("option", { name: "fake-alt · fake", exact: true }).click();
  await member.getByTestId("tutor-save").click();
  await expect(member.getByRole("status").filter({ hasText: "已保存。" })).toBeVisible();
  await member.screenshot({ path: test.info().outputPath("member-tutor.png"), fullPage: true });

  // A model outside it is refused.
  const outside = await member.request.put("/api/tutor", { data: { chat_model: "mine:gpt-x" } });
  expect(outside.status()).toBe(422);

  // The member's chat runs on the picked model: the main account's usage of them says so.
  await member.goto("/chat");
  const input = member.getByRole("textbox", { name: /输入消息/ });
  await input.fill("I goed home");
  await input.press("Enter");
  await expect(member.getByText("Nice try! You said: I goed home")).toBeVisible();
  await page.goto("/settings#usage");
  await expect(async () => {
    await page.reload();
    await page.getByText("明细（按天和模型）").click({ timeout: 2_000 });
    await page.getByRole("combobox", { name: "谁的用量" }).click({ timeout: 2_000 });
    await page.getByRole("option", { name: "Bo", exact: true }).click({ timeout: 2_000 });
    await expect(page.getByRole("table", { name: "明细（按天和模型）" })).toContainText("fake:fake-alt", {
      timeout: 2_000,
    });
  }).toPass({ timeout: 20_000 });

  await memberContext.close();
});
