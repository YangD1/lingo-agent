import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Scenario, SpeakingSession } from "@/lib/speaking";

import en from "../../../messages/en.json";
import { SpeakingList } from "./speaking-list";

const api = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  api,
}));
vi.mock("@/lib/ai-usage", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/ai-usage")>()),
  loadEstimates: () => new Promise(() => {}),
}));
const speech = vi.hoisted(() => ({ asr: true as boolean | null }));
vi.mock("@/lib/speech", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/speech")>()),
  useServerSpeech: () => ({
    languages: new Set(),
    down: false,
    noVoice: new Set(),
    shadowing: null,
    asr: speech.asr,
  }),
}));
const push = vi.hoisted(() => vi.fn());
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));

const scenario = (id: string, overrides: Partial<Scenario> = {}): Scenario => ({
  id,
  title_en: `Scene ${id}`,
  title_zh: `情景 ${id}`,
  levels: ["A2", "B1"],
  learner_goal_en: `Goal ${id}`,
  learner_goal_zh: `目标 ${id}`,
  target_expressions: ["Could I have", "the bill"],
  suits: true,
  ...overrides,
});

const session = (id: string, overrides: Partial<SpeakingSession> = {}): SpeakingSession => ({
  id,
  conversation_id: `c-${id}`,
  scenario_id: "cafe",
  mode: "cascade",
  status: "done",
  level: "A2",
  turns: 6,
  spoken_turns: 5,
  spoken_seconds: 90,
  intelligibility: "mostly",
  started_at: "2026-10-09T09:00:00Z",
  ended_at: "2026-10-09T09:10:00Z",
  ...overrides,
});

const calls: { path: string; method?: string; json?: unknown }[] = [];

function serve(sessions: SpeakingSession[], next: string | null = null) {
  api.mockImplementation(async (path: string, init?: { method?: string; json?: unknown }) => {
    calls.push({ path, method: init?.method, json: init?.json });
    if (path === "/speaking/scenarios") {
      return { level: "A2", scenarios: [scenario("cafe"), scenario("meeting", { suits: false, levels: ["B2", "C1"] })] };
    }
    if (path === "/speaking/sessions" && init?.method === "POST") return { ...session("new"), status: "active" };
    if (path === "/speaking/sessions") return { items: sessions, next_before: next };
    if (path.startsWith("/speaking/sessions?before=")) return { items: [session("old")], next_before: null };
    if (path.startsWith("/speaking/sessions/") && init?.method === "DELETE") return undefined;
    throw new Error(`unexpected ${path}`);
  });
}

function show() {
  return render(
    <NextIntlClientProvider locale="en" messages={en} timeZone="UTC">
      <SpeakingList />
    </NextIntlClientProvider>,
  );
}

beforeEach(() => {
  api.mockReset();
  push.mockReset();
  calls.length = 0;
  speech.asr = true;
});

describe("SpeakingList", () => {
  it("lists free talk and the scenarios for my level, folding the others", async () => {
    serve([]);
    show();
    const free = await screen.findByTestId("speaking-scenario-free");
    expect(free).toHaveTextContent("Free talk");
    const cafe = screen.getByTestId("speaking-scenario-cafe");
    expect(cafe).toHaveTextContent("Scene cafe");
    expect(cafe).toHaveTextContent("A2–B1");
    expect(cafe).toHaveTextContent("Could I have");
    expect(screen.getByText("1 more situation outside A2")).toBeInTheDocument();
    expect(screen.getByTestId("speaking-scenario-meeting")).not.toBeVisible();
    expect(screen.queryByTestId("speaking-no-asr")).not.toBeInTheDocument();
    expect(screen.queryByTestId("speaking-continue")).not.toBeInTheDocument();
  });

  it("starts a practice and opens it", async () => {
    serve([]);
    show();
    await userEvent.click(await screen.findByTestId("speaking-scenario-cafe"));
    expect(calls.find((c) => c.method === "POST")?.json).toEqual({ scenario_id: "cafe", locale: "en" });
    expect(push).toHaveBeenCalledWith("/speaking/new");

    await userEvent.click(screen.getByTestId("speaking-scenario-free"));
    expect(calls.filter((c) => c.method === "POST")).toHaveLength(1); // still starting
  });

  it("offers the open practice first, lists past ones and deletes one", async () => {
    serve([session("a", { status: "active", intelligibility: null, turns: 3 }), session("b")], "cursor");
    show();
    const open = await screen.findByTestId("speaking-continue");
    expect(open).toHaveAttribute("href", "/speaking/a");
    expect(open).toHaveTextContent("Scene cafe");
    expect(open).toHaveTextContent("3 turns");

    const rows = screen.getAllByTestId("speaking-session");
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent("In progress");
    expect(rows[1]).toHaveTextContent("spoke 1.5 min");
    expect(rows[1]).toHaveTextContent("Mostly clear");

    await userEvent.click(screen.getByRole("button", { name: "Load earlier" }));
    expect(await screen.findAllByTestId("speaking-session")).toHaveLength(3);

    await userEvent.click(within(rows[1]).getByRole("button", { name: "Delete" }));
    await userEvent.click(within(rows[1]).getByRole("button", { name: "Delete" }));
    expect(calls.at(-1)).toEqual({ path: "/speaking/sessions/b", method: "DELETE", json: undefined });
    expect(screen.getAllByTestId("speaking-session")).toHaveLength(2);
  });

  it("says voice needs speech-to-text when it isn't set up", async () => {
    speech.asr = false;
    serve([]);
    show();
    expect(await screen.findByTestId("speaking-no-asr")).toHaveTextContent("you can still type");
  });
});
