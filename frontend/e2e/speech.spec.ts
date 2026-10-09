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

// Server read-aloud (ADR 0028 §3, task 54): a made-up audio element that "plays" a
// sentence in 50ms and records what it was given, instead of sound.
async function fakeAudio(page: Page) {
  await page.addInitScript(() => {
    const played: string[] = [];
    Object.assign(window, { __played: played });
    class FakeAudio {
      src = "";
      onended: (() => void) | null = null;
      onerror: (() => void) | null = null;
      paused = true;
      play() {
        const src = this.src;
        this.paused = false;
        if (!src.startsWith("data:")) played.push(src); // not the moment of silence
        setTimeout(() => {
          if (this.src === src && !this.paused) this.onended?.();
        }, 50);
        return Promise.resolve();
      }
      pause() {
        this.paused = true;
      }
    }
    Object.defineProperty(window, "Audio", { value: FakeAudio, configurable: true });
  });
}

const played = (page: Page) =>
  page.evaluate(() => (window as unknown as { __played: string[] }).__played);

async function readAloudRoute(page: Page, model: string) {
  const route = await page.request.put("/api/tenant/routes/tts/default", {
    data: { models: [`fake:${model}`] },
  });
  expect(route.status()).toBe(200);
}

test("a read-aloud route reads replies on the server, from the cache the second time", async ({
  page,
}) => {
  await fakeVoices(page, [ZIRA, XIAOXIAO]);
  await fakeAudio(page);
  await register(page, uniqueEmail());
  await useFakeModel(page);
  await readAloudRoute(page, "fake-tts");
  const cached: string[] = [];
  page.on("response", (response) => {
    if (response.url().endsWith("/api/speech/tts")) cached.push(response.headers()["x-tts-cached"]);
  });
  await page.goto("/chat");

  await chat(page, "apples");
  const reply = page.locator('li[data-role="assistant"]').last();
  await expect(reply.locator('[data-slot="message"]')).toContainText("You said");
  // The server's voice costs something: the button says it uses AI.
  await expect(reply.getByTestId("ai-badge-read_aloud")).toBeVisible();
  const read = reply.getByRole("button", { name: "朗读", exact: true });
  await read.click();

  // Sentence by sentence, the second fetched while the first plays; nothing for the browser.
  await expect.poll(() => cached).toEqual(["0", "0"]);
  await expect(read).toBeVisible(); // done reading
  expect(await played(page)).toHaveLength(2);
  expect(await spoken(page)).toEqual([]);

  await read.click();
  await expect.poll(() => cached).toEqual(["0", "0", "1", "1"]);
  await expect(read).toBeVisible();

  // The usage page counts the characters read; the learner can clear their recordings.
  await expect(async () => {
    await page.goto("/settings"); // usage is written in the background
    await expect(page.locator("#usage")).toContainText("朗读字符", { timeout: 2_000 });
  }).toPass({ timeout: 20_000 });
  const card = page.locator("#read-aloud");
  await expect(card.getByTestId("speech-server")).toBeChecked();
  await card.getByRole("button", { name: "清除我的朗读缓存" }).click();
  await card.getByRole("button", { name: "清除", exact: true }).click();
  await expect(card.getByText("已删除 2 段录音。")).toBeVisible();
});

test("when the read-aloud service fails, the browser reads instead", async ({ page }) => {
  await fakeVoices(page, [ZIRA, XIAOXIAO]);
  await fakeAudio(page);
  await register(page, uniqueEmail());
  await useFakeModel(page);
  await readAloudRoute(page, "fake-tts-broken");
  await page.goto("/chat");

  await chat(page, "apples");
  const reply = page.locator('li[data-role="assistant"]').last();
  await expect(reply.locator('[data-slot="message"]')).toContainText("You said");
  await reply.getByRole("button", { name: "朗读", exact: true }).click();

  await expect.poll(async () => (await spoken(page)).map((u) => u.text)).toEqual([
    "Nice try!",
    "You said: apples",
  ]);
  expect(await played(page)).toEqual([]);
  // For the rest of the page the device reads, and the settings say why.
  await expect(reply.getByTestId("ai-badge-read_aloud")).toHaveCount(0);
  await reply.getByRole("button", { name: "朗读设置" }).click();
  await expect(page.getByTestId("speech-settings")).toContainText("朗读服务在这个页面暂时不可用");
});

test("the read-aloud route takes a voice per language in settings", async ({ page }) => {
  await register(page, uniqueEmail());
  await useFakeModel(page);
  await readAloudRoute(page, "fake-tts");
  await page.goto("/settings");

  const card = page.getByTestId("route-tts");
  await expect(card).toContainText("fake:fake-tts");
  await card.getByRole("button", { name: "调整顺序" }).click();
  const british = card.getByLabel("第 1 个模型的英音声音");
  await expect(british).toHaveAttribute("placeholder", "默认：coral");
  await british.fill("fable");
  await british.press("Escape");
  await card.getByRole("button", { name: "保存", exact: true }).click();

  await expect(card).toContainText("英音 fable");
  const routes = await (await page.request.get("/api/tenant/routes")).json();
  const tts = routes.find((r: { section: string }) => r.section === "tts");
  expect(tts.params).toEqual({ voices: { "fake:fake-tts": { "en-GB": "fable" } } });
});
