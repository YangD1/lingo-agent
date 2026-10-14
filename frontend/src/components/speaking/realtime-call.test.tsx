import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Activity } from "@/lib/activity";
import { type CallLine, type CallState, initialCall } from "@/lib/realtime-call";

import en from "../../../messages/en.json";
import { clock, RealtimeCallPage } from "./realtime-call";

const api = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  api,
}));
vi.mock("@/lib/ai-usage", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/ai-usage")>()),
  loadEstimates: () => new Promise(() => {}),
}));
const replace = vi.hoisted(() => vi.fn());
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace }) }));

const call = vi.hoisted(() => ({
  state: null as unknown as CallState,
  level: 0,
  muted: false,
  start: vi.fn(),
  hangUp: vi.fn(),
  setMuted: vi.fn(),
  dismissEnd: vi.fn(),
}));
vi.mock("./use-realtime-call", () => ({ useRealtimeCall: () => call }));

const LIVE: CallState = {
  ...initialCall,
  phase: "live",
  session_id: "s1",
  conversation_id: "c1",
  input_rate: 24000,
  output_rate: 24000,
  limit_seconds: 900,
  elapsed: 65,
};

const tool = (name: string, summary: Record<string, unknown>, status: Activity["status"] = "ok"): CallLine => ({
  kind: "tool",
  activity: { turn_id: "m1", name, kind: "tool", call_id: `call-${name}-${JSON.stringify(summary)}`, status, duration_ms: 5, summary },
});

function show(state: Partial<CallState>, scenarioId: string | null = null) {
  call.state = { ...LIVE, ...state };
  return render(
    <NextIntlClientProvider locale="en" messages={en}>
      <RealtimeCallPage scenarioId={scenarioId} />
    </NextIntlClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  window.localStorage.clear();
  call.muted = false;
  api.mockImplementation(async (path: string) => {
    if (path === "/speaking/scenarios") {
      return {
        level: "B1",
        scenarios: [
          {
            id: "cafe",
            title_en: "At a café",
            title_zh: "在咖啡馆",
            levels: ["A2", "B1"],
            learner_goal_en: "Order a drink",
            learner_goal_zh: "点一杯饮料",
            target_expressions: ["Could I have"],
            suits: true,
          },
        ],
      };
    }
    return {};
  });
});

describe("clock", () => {
  it("shows minutes and seconds", () => {
    expect(clock(0)).toBe("0:00");
    expect(clock(65)).toBe("1:05");
    expect(clock(900)).toBe("15:00");
  });
});

describe("RealtimeCallPage", () => {
  it("connects on the click, with the scenario, and says it uses AI", async () => {
    show({ ...initialCall }, "cafe");
    expect(await screen.findByRole("heading", { name: "At a café" })).toBeInTheDocument();
    expect(screen.getByText("Order a drink")).toBeInTheDocument();
    expect(screen.getByText(/Headphones work best/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /uses AI/i })).toBeInTheDocument();
    await userEvent.click(screen.getByTestId("call-connect"));
    expect(call.start).toHaveBeenCalledWith("cafe");
  });

  it("calls free talk without a scenario", async () => {
    show({ ...initialCall });
    expect(screen.getByRole("heading", { name: "Free talk" })).toBeInTheDocument();
    await userEvent.click(screen.getByTestId("call-connect"));
    expect(call.start).toHaveBeenCalledWith(null);
  });

  it("can cancel while connecting", async () => {
    show({ ...initialCall, phase: "connecting" });
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(call.hangUp).toHaveBeenCalled();
  });

  it("shows both sides' subtitles, the time left and the hang-up button", async () => {
    show({
      lines: [
        { kind: "subtitle", role: "tutor", item_id: "t1", text: "How was your day?", final: true },
        { kind: "subtitle", role: "learner", item_id: null, text: "", final: false },
        { kind: "subtitle", role: "tutor", item_id: "t2", text: "Tell me", final: false },
      ],
    });
    expect(screen.getByText("How was your day?")).toBeInTheDocument();
    expect(screen.getByLabelText("Listening…")).toBeInTheDocument();
    expect(screen.getByText("Tell me").closest("li")).toHaveAttribute("data-final", "false");
    expect(screen.getByTestId("call-time-left")).toHaveTextContent("13:55");
    // No way back mid-call but hanging up.
    expect(screen.queryByRole("link", { name: "Back to speaking" })).not.toBeInTheDocument();
    await userEvent.click(screen.getByTestId("call-hang-up"));
    expect(call.hangUp).toHaveBeenCalled();
  });

  it("hides the assistant's subtitles for listening practice and remembers it", async () => {
    show({
      lines: [
        { kind: "subtitle", role: "tutor", item_id: "t1", text: "Secret words", final: true },
        { kind: "subtitle", role: "learner", item_id: "l1", text: "My words", final: true },
      ],
    });
    await userEvent.click(screen.getByRole("button", { name: "Hide the assistant's subtitles" }));
    expect(screen.queryByText("Secret words")).not.toBeInTheDocument();
    expect(screen.getByText("(subtitles hidden)")).toBeInTheDocument();
    expect(screen.getByText("My words")).toBeInTheDocument();
    expect(window.localStorage.length).toBeGreaterThan(0);
  });

  it("shows what the assistant did, and a word just added can be taken off", async () => {
    show({
      lines: [
        tool("lookup_word", { word: "sustainable", word_id: 7 }),
        tool("lookup_word", { word: "blorft", word_id: null }),
        tool("add_to_vocab", { added: [{ word_id: 7, word: "sustainable" }], existing: [] }),
        tool("add_to_vocab", { added: [], existing: [{ word_id: 8, word: "habit" }] }),
        tool("add_to_vocab", { added: [], existing: [] }),
        tool("add_to_vocab", {}, "failed"),
        tool("end_session", {}),
      ],
    });
    expect(screen.getByText("Looked up sustainable")).toBeInTheDocument();
    expect(screen.getByText(/blorft isn't in the dictionary/)).toBeInTheDocument();
    expect(screen.getByText("habit is already on your word list")).toBeInTheDocument();
    expect(screen.getByText("Not in the dictionary, so not added")).toBeInTheDocument();
    expect(screen.getByText("Adding the word failed")).toBeInTheDocument();
    // end_session is the banner, not a line.
    expect(screen.getAllByTestId("call-tool")).toHaveLength(6);

    expect(screen.getAllByRole("button", { name: "Undo" })).toHaveLength(1);
    await userEvent.click(screen.getByRole("button", { name: "Undo" }));
    expect(api).toHaveBeenCalledWith("/vocab/mine/7", expect.objectContaining({ method: "DELETE" }));
    expect(await screen.findByText("Removed from your word list")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Undo" })).not.toBeInTheDocument();
  });

  it("offers hanging up when the assistant suggests it; the learner decides", async () => {
    show({ end_suggested: true });
    expect(screen.getByTestId("call-end-suggested")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Keep talking" }));
    expect(call.dismissEnd).toHaveBeenCalled();
    expect(call.hangUp).not.toHaveBeenCalled();
    const hangUps = screen.getAllByRole("button", { name: "Hang up" });
    await userEvent.click(hangUps[0]);
    expect(call.hangUp).toHaveBeenCalled();
  });

  it("warns near the end and says goodbye at the limit", () => {
    const { unmount } = show({ warned: true, elapsed: 840 });
    expect(screen.getByText("About a minute left.")).toBeInTheDocument();
    expect(screen.getByTestId("call-time-left")).toHaveClass("text-destructive");
    unmount();
    show({ phase: "wrapping", elapsed: 900 });
    expect(screen.getByText(/Time's up: your assistant is saying goodbye/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Mute" })).toBeDisabled();
  });

  it("mutes", async () => {
    show({});
    await userEvent.click(screen.getByRole("button", { name: "Mute" }));
    expect(call.setMuted).toHaveBeenCalledWith(true);
  });

  it("asks before the tab closes mid-call", () => {
    show({});
    const event = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(true);
  });

  it("does not ask once the call is over", () => {
    show({ phase: "ended", session_id: null, end_reason: "hangup" });
    const event = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(false);
  });

  it("goes on to the call's transcript and summary once it ends", () => {
    show({ phase: "ended", end_reason: "time_limit" });
    expect(replace).toHaveBeenCalledWith("/speaking/s1?call_end=time_limit");
  });

  it("says why a call was refused, with settings when an admin can fix it", () => {
    show({ ...initialCall, phase: "ended", end_reason: "refused", refused_code: "no_realtime_model" });
    expect(screen.getByRole("alert")).toHaveTextContent(/No realtime voice model/);
    expect(screen.getByRole("link", { name: "Go to settings" })).toHaveAttribute("href", "/settings");
    expect(replace).not.toHaveBeenCalled();
  });

  it("offers no retry when today's minutes are used up", () => {
    show({ ...initialCall, phase: "ended", end_reason: "refused", refused_code: "realtime_used_up" });
    expect(screen.getByRole("alert")).toHaveTextContent(/used today's call minutes/);
    expect(screen.queryByRole("button", { name: "Try again" })).not.toBeInTheDocument();
  });

  it("retries a call that could not begin", async () => {
    show({ ...initialCall, phase: "ended", end_reason: "microphone_denied" }, "cafe");
    expect(screen.getByRole("alert")).toHaveTextContent(/No microphone permission/);
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(call.start).toHaveBeenCalledWith("cafe");
  });

  it("says how long to wait after calling too often, and offers a retry", () => {
    show({
      ...initialCall,
      phase: "ended",
      end_reason: "refused",
      refused_code: "rate_limited",
      retry_after: 25,
    });
    expect(screen.getByRole("alert")).toHaveTextContent("Too many calls just now. Try again in 25 s.");
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });

  it("falls back to a general text for an unknown refusal", () => {
    show({ ...initialCall, phase: "ended", end_reason: "refused", refused_code: "something_new" });
    expect(screen.getByRole("alert")).toHaveTextContent("The call couldn't be connected.");
  });
});
