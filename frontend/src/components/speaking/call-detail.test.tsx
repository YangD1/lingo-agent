import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ConversationActivity } from "@/lib/activity";
import type { SpeakingSessionDetail } from "@/lib/speaking";

import en from "../../../messages/en.json";
import { CALL_POLL_MS } from "./call-transcript";
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
const push = vi.hoisted(() => vi.fn());
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));

const call = (overrides: Partial<SpeakingSessionDetail> = {}): SpeakingSessionDetail => ({
  id: "s1",
  conversation_id: "c1",
  scenario_id: "cafe",
  mode: "realtime",
  status: "done",
  level: "B1",
  turns: 4,
  spoken_turns: 2,
  spoken_seconds: 180,
  intelligibility: "mostly",
  started_at: "2026-10-11T09:00:00Z",
  ended_at: "2026-10-11T09:03:00Z",
  summary: {
    went_well: ["Clear greetings"],
    mistakes: [],
    more_natural: [],
    next_expressions: [],
    intelligibility: "mostly",
  },
  corrected_message_ids: [],
  ...overrides,
});

const done = (overrides: Partial<ConversationActivity> = {}): ConversationActivity => ({
  activities: [
    {
      turn_id: "l1",
      name: "add_to_vocab",
      kind: "tool",
      call_id: "x1",
      status: "ok",
      duration_ms: 5,
      summary: { added: [{ word_id: 7, word: "latte" }], existing: [] },
    },
  ],
  memories: {},
  kcs: {},
  words_on_list: [7],
  pending: false,
  ...overrides,
});

let session: SpeakingSessionDetail;
let activity: ConversationActivity;

function serve() {
  api.mockImplementation(async (path: string, init?: { method?: string }) => {
    if (path === "/speaking/sessions/s1") return session;
    if (path === "/speaking/sessions/s1/end" && init?.method === "POST") {
      session = call();
      return session;
    }
    if (path === "/speaking/scenarios") {
      return {
        level: "B1",
        scenarios: [
          {
            id: "cafe",
            title_en: "Ordering coffee",
            title_zh: "点咖啡",
            levels: ["A1", "B1"],
            learner_goal_en: "Order a drink.",
            learner_goal_zh: "点一杯饮料。",
            target_expressions: [],
            suits: true,
          },
        ],
      };
    }
    if (path === "/conversations/c1/messages") {
      return [
        { id: "t1", role: "assistant", content: "Hi! What can I get you?", attachments: [], interrupted: false },
        { id: "t2", role: "assistant", content: "We have", attachments: [], interrupted: true },
        { id: "l1", role: "user", content: "A latte, please", attachments: [], interrupted: false },
      ];
    }
    if (path === "/conversations/c1/activity") return activity;
    if (path === "/vocab/mine/7" && init?.method === "DELETE") return undefined;
    throw new Error(`unexpected ${path}`);
  });
}

function show(callEnd: string | null = null) {
  return render(
    <NextIntlClientProvider locale="en" messages={en} timeZone="UTC">
      <SpeakingSessionPage id="s1" callEnd={callEnd} />
    </NextIntlClientProvider>,
  );
}

beforeEach(() => {
  api.mockReset();
  push.mockReset();
  session = call();
  activity = done();
  serve();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("a realtime call's page", () => {
  it("shows the summary, the transcript with cut-short replies, and what the tutor did", async () => {
    show();
    expect(await screen.findByText("Clear greetings")).toBeInTheDocument();
    expect(screen.getByText("called 3 min")).toBeInTheDocument();
    const transcript = await screen.findByTestId("call-transcript");
    const lines = within(transcript).getAllByRole("listitem");
    expect(lines.map((l) => l.getAttribute("data-role"))).toEqual(["assistant", "assistant", "user"]);
    expect(lines[1]).toHaveTextContent("We have");
    expect(lines[1]).toHaveTextContent("cut short");
    expect(lines[0]).not.toHaveTextContent("cut short");
    expect(screen.getByText(/may differ a little from what the tutor heard/)).toBeInTheDocument();

    await userEvent.click(
      await screen.findByRole("button", { name: "What the tutor did: added 1 word to your word list" }),
    );
    await userEvent.click(screen.getByRole("button", { name: "Remove latte from your word list" }));
    expect(api).toHaveBeenCalledWith("/vocab/mine/7", expect.objectContaining({ method: "DELETE" }));
    expect(await screen.findByText("removed")).toBeInTheDocument();
  });

  it("calls again rather than starting push-to-talk", async () => {
    show();
    await userEvent.click(await screen.findByRole("button", { name: "Call again" }));
    expect(push).toHaveBeenCalledWith("/speaking/call?scenario=cafe");
    expect(api).not.toHaveBeenCalledWith("/speaking/sessions", expect.anything());
  });

  it("says why it ended when it was not the learner hanging up", async () => {
    show("time_limit");
    expect(await screen.findByTestId("call-end-note")).toHaveTextContent("Time was up");
  });

  it("says nothing more when the learner hung up", async () => {
    show("hangup");
    await screen.findByText("Clear greetings");
    expect(screen.queryByTestId("call-end-note")).not.toBeInTheDocument();
  });

  it("waits for the summary and the reflection, asking again until they are done", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    session = call({ status: "active", summary: null, intelligibility: null });
    activity = done({ activities: [], pending: true });
    show();
    expect(await screen.findByTestId("speaking-summarizing")).toHaveTextContent("Going over the call");

    session = call();
    activity = done();
    await act(() => vi.advanceTimersByTimeAsync(CALL_POLL_MS));
    expect(await screen.findByText("Clear greetings")).toBeInTheDocument();
    expect(
      await screen.findByRole("button", { name: "What the tutor did: added 1 word to your word list" }),
    ).toBeInTheDocument();
    const asked = api.mock.calls.length;
    await act(() => vi.advanceTimersByTimeAsync(CALL_POLL_MS * 3));
    expect(api.mock.calls.length).toBe(asked); // done: no more asking
  });

  it("says when a call is still going on elsewhere", async () => {
    session = call({ status: "active", summary: null, ended_at: null });
    show();
    expect(await screen.findByTestId("speaking-summarizing")).toHaveTextContent("hasn't ended yet");
  });

  it("explains a call too short for a summary", async () => {
    session = call({ summary: null, intelligibility: null, spoken_seconds: 20 });
    show();
    expect(await screen.findByText(/shorter than 30 seconds/)).toBeInTheDocument();
  });

  it("retries a summary that failed", async () => {
    session = call({ status: "failed", summary: null });
    show();
    await userEvent.click(await screen.findByRole("button", { name: /Try again/ }));
    expect(await screen.findByText("Clear greetings")).toBeInTheDocument();
  });

  it("says when nothing was transcribed", async () => {
    api.mockImplementation(async (path: string) => {
      if (path === "/conversations/c1/messages") return [];
      if (path === "/speaking/sessions/s1") return session;
      if (path === "/conversations/c1/activity") return done({ activities: [] });
      if (path === "/speaking/scenarios") return { level: "B1", scenarios: [] };
      throw new Error(`unexpected ${path}`);
    });
    show();
    expect(await screen.findByText("Nothing was transcribed on this call.")).toBeInTheDocument();
  });
});
