import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import type { SpeakingSessionDetail } from "@/lib/speaking";
import type { ChatEvent } from "@/lib/sse";

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
vi.mock("@/lib/speech", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/speech")>()),
  useCanSpeak: () => true,
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
});
