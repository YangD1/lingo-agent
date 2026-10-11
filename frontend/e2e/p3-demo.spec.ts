import { expect, type Page, test } from "@playwright/test";

import { FAKE_LLM_URL, register, uniqueEmail, useFakeModel } from "./helpers";

// The whole of P3 in one learner's day (task 64, Q64a), on the fake model and Chromium's
// fake microphone: a reply read aloud by the server and shadowed → today's speaking
// practice → a realtime call → words heard and picked on the review cards → the
// dashboard and the learner model. Each step has its own spec; this one checks they add up.
test.use({
  locale: "zh-CN",
  launchOptions: {
    args: ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"],
  },
});

const SENTENCE = "You said: I went home.";
const WORD = "serendipity";
// A call's summary is only made for 30 seconds or more (Q61g).
const SUMMARY_SECONDS = 31;

const messages = (page: Page) =>
  page.getByRole("list", { name: "消息" }).locator(':scope > li > [data-slot="message"]');

async function route(page: Page, section: string, model: string) {
  const response = await page.request.put(`/api/tenant/routes/${section}/default`, {
    data: { models: [model] },
  });
  expect(response.status()).toBe(200);
}

async function connect(page: Page, data: Record<string, unknown>) {
  const response = await page.request.post("/api/tenant/connections", { data });
  expect(response.status()).toBe(201);
}

/**
 * Every P3 route on the fake server (the settings UI has its own specs): read-aloud,
 * transcription, pronunciation assessment by the fake Azure, and realtime calls.
 */
async function useFakeVoice(page: Page) {
  const root = FAKE_LLM_URL.replace(/\/v1$/, "");
  await route(page, "tts", "fake:fake-tts");
  await route(page, "asr", "fake:fake-whisper");
  await connect(page, {
    name: "speech",
    kind: "azure_speech",
    base_url: root,
    api_key: "fake-azure-key",
  });
  await route(page, "pronunciation", "speech:pronunciation");
  await connect(page, {
    name: "voice",
    kind: "openai_compatible",
    base_url: FAKE_LLM_URL,
    api_key: "sk-fake",
    params: {
      realtime_url: `${FAKE_LLM_URL.replace(/^http/, "ws")}/realtime`,
      realtime_dialect: "ga",
    },
  });
  await route(page, "realtime", "voice:fake-realtime");
}

/** Plays the server's recordings without sound, recording what was played. */
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
        if (!src.startsWith("data:")) played.push(src);
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

/** One push-to-talk turn; the fake microphone beeps now and then, so give it 3 seconds. */
async function talk(page: Page) {
  const mic = page.getByTestId("speaking-mic");
  await mic.click();
  await expect(mic).toHaveAttribute("data-recording", "true");
  await page.waitForTimeout(3_000);
  await mic.click();
}

test("P3 demo: read aloud and shadowed, today's speaking, a call, words by ear", async ({
  page,
}) => {
  test.setTimeout(240_000);
  await fakeAudio(page);
  await register(page, uniqueEmail());
  await useFakeModel(page);
  await useFakeVoice(page);

  // 1. A reply read aloud by the server, then one of its sentences shadowed and scored.
  await page.goto("/chat");
  const input = page.getByRole("textbox", { name: /输入消息/ });
  await input.fill("I went home.");
  await input.press("Enter");
  await expect(messages(page).nth(1)).toContainText(SENTENCE);
  const reply = page.locator('li[data-role="assistant"]').last();
  const read = reply.getByRole("button", { name: "朗读", exact: true });
  await read.click();
  await expect.poll(async () => (await played(page)).length).toBeGreaterThan(0);

  await page.getByTestId("shadowing-open").click();
  const panel = page.getByTestId("shadowing-panel");
  await panel.getByRole("button", { name: SENTENCE }).click();
  await panel.getByRole("button", { name: "开始录音" }).click();
  await expect(panel.getByText("3 / 30 秒")).toBeVisible({ timeout: 10_000 });
  await panel.getByRole("button", { name: "读完了" }).click();
  await expect(panel.getByTestId("shadowing-result")).toHaveAttribute("data-mode", "assessment");
  await expect(panel.getByTestId("shadowing-overall")).toHaveText("84");

  // 2. Today's plan with speaking switched on (it's never in the draft, Q59d).
  await page.goto("/dashboard");
  const plan = page.getByTestId("today-plan");
  await expect(plan).toHaveAttribute("data-status", "proposed");
  await plan.getByTestId("plan-row-speaking").getByRole("switch").click();
  await plan.getByRole("button", { name: "确认计划" }).click();
  const speaking = plan.getByTestId("plan-item-speaking");
  await expect(speaking.getByTestId("plan-progress")).toHaveText("0/5 分钟");

  // 3. The plan's speaking practice: two voice turns of 150 seconds each (e2e/fake_llm.py).
  await speaking.getByRole("link", { name: "去说" }).click();
  await page.getByTestId("speaking-scenario-self_intro").click();
  await expect(messages(page).nth(0)).toContainText("What's your name?");
  await talk(page);
  await expect(messages(page).nth(2)).toContainText("You said: I goed home yesterday.");
  await talk(page);
  await expect(messages(page).nth(4)).toContainText("You said: I goed home yesterday.");
  await page.getByTestId("speaking-end").click();
  const summary = page.getByTestId("speaking-summary");
  await expect(summary).toHaveAttribute("data-status", "done");
  await expect(summary).toContainText("说了 5 分钟");
  await expect(page.getByTestId("summary-mistakes")).toContainText("I went home");

  // 4. A realtime call on the same scenario: the tutor looks a word up and adds it; the
  // learner takes it off again, so it doesn't come into the review queue below.
  await page.goto("/speaking");
  await page.getByTestId("speaking-call-self_intro").click();
  const call = page.getByTestId("realtime-call");
  await page.getByTestId("call-connect").click();
  const connected = Date.now();
  await expect(call).toHaveAttribute("data-phase", "live");
  const added = call.getByTestId("call-tool").filter({ hasText: `已把 ${WORD} 加入生词本` });
  await expect(added).toBeVisible();
  await added.getByRole("button", { name: "撤销" }).click();
  await expect(call.getByText("已从生词本移除")).toBeVisible();
  await expect(page.getByTestId("call-end-suggested")).toBeVisible();
  await page.waitForTimeout(Math.max(0, SUMMARY_SECONDS * 1000 - (Date.now() - connected)));
  await page.getByTestId("call-hang-up").click();
  await expect(page).toHaveURL(/\/speaking\/[\w-]+\?call_end=hangup$/);
  await expect(page.getByTestId("speaking-summary")).toHaveAttribute("data-status", "done", {
    timeout: 20_000,
  });
  await expect(page.getByTestId("call-transcript")).toContainText(`What does "${WORD}" mean?`);

  // 5. Review: a word missed once comes back to be heard and its meaning picked.
  const book = await page.request.put("/api/vocab/book", { data: { book_id: "oxford3000" } });
  expect(book.status()).toBe(204);
  await page.goto("/vocab/review");
  await page.getByRole("radio", { name: "听音" }).click();
  const listen = page.getByTestId("review-listen");
  // New words are shown as words whatever the type: miss "the", know the rest.
  const word = page.locator('h1[lang="en"]');
  for (let n = 0; ; n++) {
    expect(n).toBeLessThan(12);
    await expect(word.or(listen)).toBeVisible();
    if (await listen.isVisible()) break;
    const missed = (await word.textContent())?.trim() === "the";
    await page.keyboard.press("Space");
    await page.keyboard.press(missed ? "1" : "4");
    // The next card is on screen once the count moves.
    await expect(page.getByTestId("review-progress")).toContainText(`已复习 ${n + 1}`);
  }
  await expect(page.getByRole("heading", { name: "the", exact: true })).toHaveCount(0);
  await listen.getByRole("button", { name: "art. 那" }).click();
  await expect(page.getByTestId("review-result")).toHaveText("选对了");
  await page.keyboard.press("Enter");

  // 6. The dashboard: today's speaking done.
  await page.goto("/dashboard");
  await expect(speaking).toHaveAttribute("data-complete", "true");
  await expect(speaking.getByTestId("plan-progress")).toHaveText(/^\d+\/5 分钟$/);

  // 7. The learner model: speaking assessed, the shadowing kept; the speaking history.
  await page.goto("/learner");
  await expect(page.getByTestId("skill-speaking")).not.toContainText("未评估");
  const shadowed = page.getByTestId("learner-shadowing").getByTestId("shadowing-item");
  await expect(shadowed).toHaveCount(1);
  await expect(shadowed).toContainText(SENTENCE);
  await page.goto("/speaking");
  const sessions = page.getByTestId("speaking-session");
  await expect(sessions).toHaveCount(2);
  await expect(sessions.filter({ hasText: "通话" })).toHaveCount(1);
});
