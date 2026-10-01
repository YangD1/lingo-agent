import { expect, type Page, test } from "@playwright/test";

import { register, uniqueEmail, useFakeModel } from "./helpers";

test.use({ locale: "zh-CN" });

// ADR 0018: the browser's voices, picked and set per device. Headless Chromium has no
// voices of its own, so each page gets a made-up device: these voices, and a record of
// what it was asked to read instead of sound.

type FakeVoice = { name: string; lang: string; localService: boolean };
type Spoken = { text: string; lang: string; voice: string | null; rate: number };

const ZIRA = { name: "Microsoft Zira - English (United States)", lang: "en-US", localService: true };
const ARIA = {
  name: "Microsoft Aria Online (Natural) - English (United States)",
  lang: "en-US",
  localService: false,
};
const SONIA = {
  name: "Microsoft Sonia Online (Natural) - English (United Kingdom)",
  lang: "en-GB",
  localService: false,
};
const XIAOXIAO = {
  name: "Microsoft Xiaoxiao Online (Natural) - Chinese (Mainland)",
  lang: "zh-CN",
  localService: false,
};

/** `silentOnline`: a network that can't reach the online voices' servers. */
async function fakeVoices(page: Page, voices: FakeVoice[], { silentOnline = false } = {}) {
  await page.addInitScript(([list, silent]: [FakeVoice[], boolean]) => {
    const all = list.map((v) => ({ ...v, default: false, voiceURI: v.name }));
    const spoken: Spoken[] = [];
    Object.assign(window, { __spoken: spoken });
    class Utterance {
      lang = "";
      voice: { name: string; localService: boolean } | null = null;
      rate = 1;
      onstart: (() => void) | null = null;
      onend: (() => void) | null = null;
      onerror: (() => void) | null = null;
      constructor(public text: string) {}
    }
    // Reads one piece at a time, like a browser; a silent voice never starts.
    let queue: Utterance[] = [];
    const next = () => {
      const u = queue[0];
      if (!u || (silent && u.voice && !u.voice.localService)) return;
      setTimeout(() => {
        if (queue[0] !== u) return;
        u.onstart?.();
        queue.shift();
        u.onend?.();
        next();
      }, 50);
    };
    const synth = {
      getVoices: () => all,
      addEventListener: () => {},
      cancel: () => {
        queue = [];
      },
      speak: (u: Utterance) => {
        spoken.push({ text: u.text, lang: u.lang, voice: u.voice?.name ?? null, rate: u.rate });
        queue.push(u);
        if (queue.length === 1) next();
      },
    };
    Object.defineProperty(window, "speechSynthesis", { value: synth, configurable: true });
    Object.defineProperty(window, "SpeechSynthesisUtterance", { value: Utterance, configurable: true });
  }, [voices, silentOnline] as [FakeVoice[], boolean]);
}

const spoken = (page: Page) =>
  page.evaluate(() => (window as unknown as { __spoken: Spoken[] }).__spoken);

async function chat(page: Page, text: string) {
  const input = page.getByRole("textbox", { name: /输入消息/ });
  await input.fill(text);
  await input.press("Enter");
  await expect(page.getByRole("button", { name: "发送" })).toBeVisible();
}

test("without a Chinese voice, only the English is read, and the learner is told", async ({
  page,
}) => {
  await fakeVoices(page, [ZIRA, ARIA]);
  await register(page, uniqueEmail());
  await useFakeModel(page);
  await page.goto("/chat");

  await chat(page, "我喜欢 apples");
  const reply = page.locator('li[data-role="assistant"]').last();
  await expect(reply.locator('[data-slot="message"]')).toContainText("You said");
  await reply.getByRole("button", { name: "朗读", exact: true }).click();

  await expect(page.getByTestId("no-chinese-voice")).toHaveText(
    "这台设备没有中文朗读声音，只读英文部分。",
  );
  const read = await spoken(page);
  expect(read.map((u) => u.text)).toEqual(["Nice try!", "You said:", "apples"]);
  // The natural voice, not the old local one; English a little slower by default.
  expect(read.every((u) => u.voice === ARIA.name && u.rate === 0.9)).toBe(true);
});

test("voice, accent and speed are kept in this browser and used for reading", async ({ page }) => {
  await fakeVoices(page, [ZIRA, ARIA, SONIA, XIAOXIAO]);
  await register(page, uniqueEmail());
  await page.goto("/settings");

  const card = page.locator("#read-aloud");
  const english = card.getByLabel("英文声音");
  await expect(english).toHaveValue("");
  await expect(english.locator("option:checked")).toHaveText(`自动（当前：${ARIA.name}）`);

  await card.getByLabel("英音").check();
  await expect(english.locator("option:checked")).toHaveText(`自动（当前：${SONIA.name}）`);
  await card.getByLabel("中文声音").selectOption(XIAOXIAO.name);
  const rate = card.getByLabel(/英文语速/);
  await rate.focus();
  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("ArrowRight");
  await expect(card.getByText("1.1×")).toBeVisible();

  await card.getByRole("button", { name: "试听" }).first().click();
  expect((await spoken(page)).at(-1)).toMatchObject({ voice: SONIA.name, lang: "en-GB", rate: 1.1 });

  // Still there after a reload.
  await page.reload();
  await expect(card.getByLabel("英音")).toBeChecked();
  await expect(card.getByLabel("中文声音")).toHaveValue(XIAOXIAO.name);
  await expect(card.getByText("1.1×")).toBeVisible();
});

test("online voices that make no sound give way to the device's own", async ({ page }) => {
  await fakeVoices(page, [ZIRA, ARIA, XIAOXIAO], { silentOnline: true });
  await register(page, uniqueEmail());
  await useFakeModel(page);
  await page.goto("/chat");

  await chat(page, "apples");
  const reply = page.locator('li[data-role="assistant"]').last();
  await expect(reply.locator('[data-slot="message"]')).toContainText("You said");
  await reply.getByRole("button", { name: "朗读", exact: true }).click();

  // About 3 seconds of silence, then the local voice reads it from where it stopped.
  await expect(reply.getByTestId("voice-fell-back")).toBeVisible({ timeout: 6000 });
  const read = await spoken(page);
  expect(read[0]).toMatchObject({ text: "Nice try!", voice: ARIA.name });
  expect(read.slice(-2)).toEqual([
    expect.objectContaining({ text: "Nice try!", voice: ZIRA.name }),
    expect.objectContaining({ text: "You said: apples", voice: ZIRA.name }),
  ]);

  // The settings say so, until the page is reloaded.
  await reply.getByRole("button", { name: "朗读设置" }).click();
  const english = page.getByTestId("speech-settings").getByLabel("英文声音");
  await expect(english.locator("option:checked")).toHaveText(`自动（当前：${ZIRA.name}）`);
  await expect(english.locator("option", { hasText: "播不出声" })).toHaveText(
    `${ARIA.name}（这台设备上播不出声）`,
  );
});
