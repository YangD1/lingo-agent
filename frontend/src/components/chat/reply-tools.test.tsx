import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import { speechSegments } from "@/lib/speech";

import en from "../../../messages/en.json";
import { Markdown } from "./markdown";
import { MessageList } from "./message-list";
import { readableText, translationTarget } from "./reply-tools";
import type { ChatMessage } from "./use-chat-session";

const api = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  api,
}));

// Shadowing is off unless a test turns it on (the capabilities come from the backend).
const shadowing = vi.hoisted(() => ({ mode: null as "assessment" | "rough" | null }));
vi.mock("@/lib/shadowing", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/shadowing")>()),
  useShadowingMode: () => shadowing.mode,
}));

const reply = (over: Partial<ChatMessage> = {}): ChatMessage => ({
  key: "k1",
  id: "m1",
  role: "assistant",
  content: "Good job! 你说得对。",
  ...over,
});

function wrap(messages: ChatMessage[], conversationId: string | null = "c1") {
  return render(
    <NextIntlClientProvider locale="en" messages={en} timeZone="UTC">
      <MessageList conversationId={conversationId} messages={messages} />
    </NextIntlClientProvider>,
  );
}

type Spoken = { text: string; lang: string; onend: (() => void) | null };

/** A browser that can read aloud (with these voices); returns what it was asked to read. */
function stubSpeech(voices: object[] = []) {
  const spoken: Spoken[] = [];
  const cancel = vi.fn();
  vi.stubGlobal("speechSynthesis", {
    cancel,
    speak: (u: Spoken) => spoken.push(u),
    getVoices: () => voices,
  });
  vi.stubGlobal(
    "SpeechSynthesisUtterance",
    class {
      lang = "";
      onend: (() => void) | null = null;
      onerror: (() => void) | null = null;
      constructor(public text: string) {}
    },
  );
  return { spoken, cancel };
}

beforeEach(() => {
  api.mockReset();
  shadowing.mode = null;
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("translationTarget", () => {
  it("turns mostly English into Chinese, anything else into English", () => {
    expect(translationTarget("Great job! Try saying it again.")).toBe("zh");
    expect(translationTarget("这个词的意思是 abandon：放弃。")).toBe("en");
    expect(translationTarget("123")).toBe("en");
  });
});

describe("speechSegments", () => {
  it("cuts mixed text into Chinese and English runs", () => {
    expect(speechSegments("你可以说 “I went home.” 意思是我回家了，3 点。")).toEqual([
      { text: "你可以说 “", lang: "zh-CN" },
      { text: "I went home.”", lang: "en-US" },
      { text: "意思是我回家了，3 点。", lang: "zh-CN" },
    ]);
    expect(speechSegments("  ... ")).toEqual([]);
  });
});

describe("readableText", () => {
  it("leaves out code blocks and breaks between blocks", () => {
    const { container } = render(
      <Markdown words>{"First line.\n\n- one\n- two\n\n```\ncode()\n```"}</Markdown>,
    );
    const text = readableText(container.querySelector('[data-slot="markdown"]')!);
    expect(text).not.toContain("code()");
    expect(text.replace(/\s+/g, " ").trim()).toBe("First line. one two");
  });
});

describe("ReplyTools", () => {
  it("reads a reply aloud, each language in its own voice, and stops on a second press", async () => {
    const { spoken, cancel } = stubSpeech();
    wrap([reply()]);
    await userEvent.click(screen.getByRole("button", { name: "Read aloud" }));
    expect(spoken.map(({ text, lang }) => ({ text, lang }))).toEqual([
      { text: "Good job!", lang: "en-US" },
      { text: "你说得对。", lang: "zh-CN" },
    ]);

    const stop = screen.getByRole("button", { name: "Stop" });
    expect(stop).toHaveAttribute("aria-pressed", "true");
    await userEvent.click(stop);
    expect(cancel).toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Read aloud" })).toBeInTheDocument();
  });

  it("goes back to “Read aloud” when reading ends", async () => {
    const { spoken } = stubSpeech();
    wrap([reply()]);
    await userEvent.click(screen.getByRole("button", { name: "Read aloud" }));
    act(() => spoken[spoken.length - 1].onend?.());
    expect(screen.getByRole("button", { name: "Read aloud" })).toBeInTheDocument();
  });

  it("reads only the English, and says so once, where the device has no Chinese voice", async () => {
    const aria = {
      name: "Microsoft Aria Online (Natural) - English (United States)",
      lang: "en-US",
      localService: false,
      default: true,
      voiceURI: "aria",
    };
    const { spoken } = stubSpeech([aria]);
    wrap([reply()]);
    await userEvent.click(screen.getByRole("button", { name: "Read aloud" }));
    expect(spoken.map(({ text }) => text)).toEqual(["Good job!"]);
    expect(screen.getByTestId("no-chinese-voice")).toHaveTextContent("no Chinese voice");
  });

  it("opens the read-aloud settings from the gear next to “Read aloud”", async () => {
    stubSpeech();
    wrap([reply()]);
    await userEvent.click(screen.getByRole("button", { name: "Read-aloud settings" }));
    expect(await screen.findByTestId("speech-settings")).toBeInTheDocument();
    expect(screen.getByLabelText(/English speed/)).toBeInTheDocument();
  });

  it("has no read-aloud button where the browser can't read", () => {
    wrap([reply()]);
    expect(screen.queryByRole("button", { name: "Read aloud" })).not.toBeInTheDocument();
  });

  it("shows the translation in place, and switches back without asking again", async () => {
    api.mockResolvedValue({ message_id: "m1", target: "zh", text: "做得好！再说一遍。" });
    wrap([reply({ content: "Good job! Say it again." })]);
    expect(screen.getByTestId("ai-badge-message_translate")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Show in Chinese" }));
    expect(api).toHaveBeenCalledWith("/conversations/c1/messages/m1/translate", {
      method: "POST",
      json: { target: "zh" },
    });
    const bubble = document.querySelector('[data-slot="message"]')!;
    expect(bubble).toHaveTextContent("做得好！再说一遍。");
    // Already translated: switching costs nothing, so no AI badge.
    expect(screen.queryByTestId("ai-badge-message_translate")).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Show original" }));
    expect(bubble).toHaveTextContent("Good job! Say it again.");
    await userEvent.click(screen.getByRole("button", { name: "Show in Chinese" }));
    expect(bubble).toHaveTextContent("做得好！再说一遍。");
    const translations = api.mock.calls.filter(([path]) => String(path).endsWith("/translate"));
    expect(translations).toHaveLength(1);
  });

  it("offers English for a mostly Chinese reply", () => {
    wrap([reply({ content: "这个词的意思是放弃。" })]);
    expect(screen.getByRole("button", { name: "Show in English" })).toBeInTheDocument();
  });

  it("says why a translation failed", async () => {
    api.mockRejectedValue(new ApiError(409, "no_llm_configured", "No chat model"));
    wrap([reply()]);
    await userEvent.click(screen.getByTestId("reply-translate"));
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(document.querySelector('[data-slot="message"]')).toHaveTextContent("Good job!");
  });

  it("offers nothing on a reply still streaming, or not saved", () => {
    wrap([reply({ status: "streaming" }), reply({ key: "k2", id: undefined })]);
    expect(screen.queryByTestId("reply-translate")).not.toBeInTheDocument();
  });
});

describe("shadowing a reply", () => {
  it("offers nothing while shadowing can't be scored", () => {
    wrap([reply()]);
    expect(screen.queryByTestId("shadowing-open")).not.toBeInTheDocument();
  });

  it("offers nothing for a reply without English sentences", () => {
    shadowing.mode = "assessment";
    wrap([reply({ content: "你说得对，继续加油。" })]);
    expect(screen.queryByTestId("shadowing-open")).not.toBeInTheDocument();
  });

  it("opens under the reply with its English sentences to pick from (Q57a)", async () => {
    shadowing.mode = "assessment";
    wrap([reply({ content: "Good job! 你可以说：**I have been here for two years.**" })]);
    expect(screen.getByTestId("ai-badge-shadowing")).toBeInTheDocument();

    await userEvent.click(screen.getByTestId("shadowing-open"));
    const options = screen.getByTestId("shadowing-sentences");
    expect(options).toHaveTextContent("Good job!");
    expect(options).toHaveTextContent("I have been here for two years.");
    expect(options).not.toHaveTextContent("**");

    await userEvent.click(screen.getByRole("button", { name: "Close shadowing" }));
    expect(screen.queryByTestId("shadowing-panel")).not.toBeInTheDocument();
  });

  it("marks rough shadowing with its own AI mark", () => {
    shadowing.mode = "rough";
    wrap([reply()]);
    expect(screen.getByTestId("ai-badge-shadowing_rough")).toBeInTheDocument();
  });
});
