import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import type { SpeakingSessionDetail } from "@/lib/speaking";
import type { ChatEvent } from "@/lib/sse";
import type { Attachment } from "@/lib/types";

import en from "../../../messages/en.json";
import { SpeakingSessionPage } from "./speaking-session";

const api = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  api,
}));
vi.mock("@/lib/ai-usage", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/ai-usage")>()),
  loadEstimates: () => new Promise(() => {}),
}));
const streamChat = vi.hoisted(() => vi.fn());
const streamOpening = vi.hoisted(() => vi.fn());
vi.mock("@/lib/sse", () => ({ streamChat, streamOpening, OPENING_TURN_ID: "opening" }));

// What was read aloud: each reading's pushed text, and whether it ended or was stopped.
const readings = vi.hoisted(() => [] as { text: string; ended: boolean }[]);
const stopSpeaking = vi.hoisted(() => vi.fn());
const caps = vi.hoisted(() => ({ asr: false }));
vi.mock("@/lib/speech", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/speech")>()),
  useCanSpeak: () => true,
  useServerSpeech: () => ({
    languages: new Set(),
    down: false,
    noVoice: new Set(),
    shadowing: null,
    asr: caps.asr,
  }),
  unlockSpeech: () => {},
  stopSpeaking,
  speakStream: () => {
    const reading = { text: "", ended: false };
    readings.push(reading);
    return {
      push: (text: string) => void (reading.text += text),
      end: () => void (reading.ended = true),
    };
  },
}));

// A recorder that hands over a fixed recording when stopped.
vi.mock("@/components/chat/use-recorder", async () => {
  const { useState } = await import("react");
  return {
    useRecorder: (onRecorded: (file: File) => void) => {
      const [recording, setRecording] = useState(false);
      return {
        recording,
        seconds: 0,
        level: 0,
        error: null,
        start: async () => setRecording(true),
        stop: () => {
          setRecording(false);
          onRecorded(new File(["voice"], "voice.webm", { type: "audio/webm" }));
        },
        cancel: () => setRecording(false),
      };
    },
  };
});
const attachments = vi.hoisted(() => ({
  uploadAttachment: vi.fn(),
  getAttachment: vi.fn(),
  retryAttachment: vi.fn(),
  deleteAttachment: vi.fn(async () => undefined),
}));
vi.mock("@/lib/attachments", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/attachments")>()),
  ...attachments,
}));

const audio = (overrides: Partial<Attachment> = {}): Attachment => ({
  id: "a1",
  conversation_id: "c1",
  kind: "audio",
  mime_type: "audio/webm",
  filename: "voice.webm",
  size_bytes: 5,
  status: "ready",
  text: "I want a latte.",
  meta: { duration_seconds: 2 },
  error: null,
  sent: false,
  created_at: "2026-10-10T09:01:00Z",
  ...overrides,
});

async function* reply(...tokens: string[]): AsyncGenerator<ChatEvent> {
  for (const text of tokens) yield { event: "token", text };
  yield { event: "done", message_id: "r1", turn_id: "u1", usage: {} };
}

const detail = (overrides: Partial<SpeakingSessionDetail> = {}): SpeakingSessionDetail => ({
  id: "s1",
  conversation_id: "c1",
  scenario_id: "cafe",
  mode: "cascade",
  status: "active",
  level: "A2",
  turns: 0,
  spoken_turns: 0,
  spoken_seconds: 0,
  intelligibility: null,
  started_at: "2026-10-10T09:00:00Z",
  ended_at: null,
  summary: null,
  corrected_message_ids: [],
  ...overrides,
});

let current: SpeakingSessionDetail;
let history: unknown[];

function serve() {
  api.mockImplementation(async (path: string, init?: { method?: string }) => {
    if (path === "/speaking/sessions/s1") return current;
    if (path === "/speaking/sessions/s1/end" && init?.method === "POST") {
      current = detail({ status: "done", ended_at: "2026-10-10T09:10:00Z" });
      return current;
    }
    if (path === "/speaking/scenarios") {
      return {
        level: "A2",
        scenarios: [
          {
            id: "cafe",
            title_en: "Ordering coffee",
            title_zh: "点咖啡",
            levels: ["A1", "A2"],
            learner_goal_en: "Order a drink you like.",
            learner_goal_zh: "点一杯你喜欢的饮料。",
            target_expressions: ["Could I have"],
            suits: true,
          },
        ],
      };
    }
    if (path === "/conversations/c1/messages") return history;
    if (path === "/speaking/sessions/s1/corrections" && init?.method === "POST") return undefined;
    throw new Error(`unexpected ${path}`);
  });
}

// Replies are split into word spans: match the whole bubble.
const bubble = (text: string) => (_: string, el: Element | null) =>
  el?.getAttribute("data-slot") === "message" && el.textContent === text;

function show() {
  return render(
    <NextIntlClientProvider locale="en" messages={en} timeZone="UTC">
      <SpeakingSessionPage id="s1" />
    </NextIntlClientProvider>,
  );
}

beforeEach(() => {
  api.mockReset();
  streamChat.mockReset();
  streamOpening.mockReset();
  stopSpeaking.mockReset();
  readings.length = 0;
  caps.asr = false;
  Object.values(attachments).forEach((f) => f.mockClear());
  window.localStorage.clear();
  current = detail();
  history = [];
  serve();
  streamOpening.mockImplementation(() => reply("Hi! What ", "can I get you?"));
});

describe("SpeakingSessionPage", () => {
  it("shows the scenario, and the tutor speaks first, read aloud as it streams", async () => {
    show();
    expect(await screen.findByRole("heading", { name: "Ordering coffee" })).toBeInTheDocument();
    expect(screen.getByText("Order a drink you like.")).toBeInTheDocument();
    expect(screen.getByText("Could I have")).toBeInTheDocument();
    expect(await screen.findByText(bubble("Hi! What can I get you?"))).toBeInTheDocument();
    expect(streamOpening).toHaveBeenCalledTimes(1);
    expect(readings).toEqual([{ text: "Hi! What can I get you?", ended: true }]);
    // Nothing said yet: ending sums up nothing.
    expect(screen.getByTestId("speaking-end")).toHaveTextContent(/^End$/);
  });

  it("sends a typed turn and reads the reply aloud", async () => {
    history = [{ id: "o1", role: "assistant", content: "Hello!", attachments: [] }];
    streamChat.mockImplementation(() => reply("Sure. ", "Anything else?"));
    show();
    const input = await screen.findByRole("textbox", { name: "Type in English…" });
    await userEvent.type(input, "A latte, please.{Enter}");
    expect(await screen.findByText(bubble("Sure. Anything else?"))).toBeInTheDocument();
    expect(streamOpening).not.toHaveBeenCalled();
    expect(streamChat).toHaveBeenCalledWith("c1", "A latte, please.", expect.anything());
    expect(readings).toEqual([{ text: "Sure. Anything else?", ended: true }]);
    expect(screen.getByTestId("speaking-end")).toHaveTextContent("End and sum up");
  });

  it("reads nothing with reading aloud off, and hides the text when asked", async () => {
    show();
    await userEvent.click(await screen.findByRole("button", { name: "Read replies aloud" }));
    await userEvent.click(screen.getByRole("button", { name: "Hide the tutor's text" }));
    expect(await screen.findByText(bubble("Text hidden for listening practice."))).toBeInTheDocument();
    // The opening started before the switch; the next reply isn't read.
    streamChat.mockImplementation(() => reply("OK."));
    await userEvent.type(screen.getByRole("textbox"), "Tea.{Enter}");
    await waitFor(() => expect(streamChat).toHaveBeenCalled());
    expect(readings).toHaveLength(1);
    // Preferences outlive the page (in this module): switch them back.
    await userEvent.click(screen.getByRole("button", { name: "Read replies aloud" }));
    await userEvent.click(screen.getByRole("button", { name: "Hide the tutor's text" }));
  });

  it("ends the practice and shows its summary", async () => {
    history = [
      { id: "o1", role: "assistant", content: "Hello!", attachments: [] },
      { id: "u1", role: "user", content: "Hi.", attachments: [] },
    ];
    show();
    await userEvent.click(await screen.findByTestId("speaking-end"));
    expect(stopSpeaking).toHaveBeenCalled();
    expect(await screen.findByTestId("speaking-summary")).toHaveAttribute("data-status", "done");
  });

  it("shows the summary when the practice ended elsewhere", async () => {
    history = [{ id: "o1", role: "assistant", content: "Hello!", attachments: [] }];
    streamChat.mockImplementation(() => {
      current = detail({ status: "done" });
      throw new ApiError(409, "speaking_ended", "This speaking practice has ended.");
    });
    show();
    await userEvent.type(await screen.findByRole("textbox"), "Hi.{Enter}");
    expect(await screen.findByTestId("speaking-summary")).toBeInTheDocument();
  });

  it("sends a voice turn as soon as it is transcribed, and fixes its transcript", async () => {
    caps.asr = true;
    history = [{ id: "o1", role: "assistant", content: "Hello!", attachments: [] }];
    let finish: () => void = () => {};
    attachments.uploadAttachment.mockImplementation(
      () => new Promise((resolve) => (finish = () => resolve(audio()))),
    );
    streamChat.mockImplementation(() => reply("Coming up."));
    show();
    const mic = await screen.findByTestId("speaking-mic");
    await userEvent.click(mic); // tap: start
    await userEvent.click(mic); // tap: send
    expect(await screen.findByTestId("speaking-pending")).toHaveTextContent("Transcribing…");
    expect(attachments.uploadAttachment).toHaveBeenCalledWith("c1", expect.any(File));
    finish();
    expect(await screen.findByText(bubble("Coming up."))).toBeInTheDocument();
    expect(streamChat).toHaveBeenCalledWith("c1", "", expect.objectContaining({ attachmentIds: ["a1"] }));
    expect(screen.queryByTestId("speaking-pending")).not.toBeInTheDocument();

    // The transcript was wrong: fix it and send it again.
    streamChat.mockImplementation(() => reply("One latte, then."));
    await userEvent.click(await screen.findByTestId("speaking-fix"));
    const box = screen.getByRole("textbox", { name: "What you said" });
    await userEvent.clear(box);
    await userEvent.type(box, "I want one latte.");
    await userEvent.click(screen.getByRole("button", { name: "Send the fixed text" }));
    expect(await screen.findByText(bubble("One latte, then."))).toBeInTheDocument();
    expect(api).toHaveBeenCalledWith("/speaking/sessions/s1/corrections", {
      method: "POST",
      json: { message_id: "u1" },
    });
    expect(streamChat).toHaveBeenLastCalledWith("c1", "I want one latte.", expect.anything());
    const learner = document.querySelectorAll('li[data-role="user"]');
    expect(learner[0]).toHaveAttribute("data-struck", "true");
    expect(learner[0]).toHaveTextContent("Fixed");
    // Only voice messages are fixed: the typed one has no "fix it".
    expect(screen.queryByTestId("speaking-fix")).not.toBeInTheDocument();
  });

  it("sends nothing when nothing was heard, and offers typing when it fails", async () => {
    caps.asr = true;
    history = [{ id: "o1", role: "assistant", content: "Hello!", attachments: [] }];
    attachments.uploadAttachment.mockResolvedValue(audio({ text: "  " }));
    show();
    const mic = await screen.findByTestId("speaking-mic");
    await userEvent.click(mic);
    await userEvent.click(mic);
    expect(await screen.findByTestId("speaking-pending")).toHaveTextContent("Didn't catch that");
    expect(attachments.deleteAttachment).toHaveBeenCalledWith("a1");
    expect(streamChat).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "OK" }));

    attachments.uploadAttachment.mockResolvedValue(audio({ status: "failed", text: null }));
    attachments.retryAttachment.mockResolvedValue(audio());
    streamChat.mockImplementation(() => reply("Got it."));
    await userEvent.click(mic);
    await userEvent.click(mic);
    expect(await screen.findByTestId("speaking-pending")).toHaveTextContent("Couldn't transcribe that.");
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText(bubble("Got it."))).toBeInTheDocument();
    expect(attachments.retryAttachment).toHaveBeenCalledWith("a1");

    attachments.uploadAttachment.mockResolvedValue(audio({ status: "failed", text: null }));
    await userEvent.click(mic);
    await userEvent.click(mic);
    const failed = await screen.findByTestId("speaking-pending");
    await userEvent.click(within(failed).getByRole("button", { name: "Type instead" }));
    expect(screen.getByRole("textbox", { name: "Type in English…" })).toBeInTheDocument();
  });
});
