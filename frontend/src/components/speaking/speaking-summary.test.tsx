import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import type { SpeakingSessionDetail } from "@/lib/speaking";

import en from "../../../messages/en.json";
import { SpeakingSummaryView } from "./speaking-summary";

const api = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  api,
}));
vi.mock("@/lib/ai-usage", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/ai-usage")>()),
  loadEstimates: () => new Promise(() => {}),
}));
vi.mock("@/lib/shadowing", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/shadowing")>()),
  useShadowingMode: () => "assessment",
}));
vi.mock("@/components/speech/shadowing-panel", () => ({
  ShadowingPanel: ({ sentences, source, sourceId }: { sentences: string[]; source: string; sourceId: string }) => (
    <div data-testid="shadowing-panel">{`${source}:${sourceId}:${sentences.join("|")}`}</div>
  ),
}));
const push = vi.hoisted(() => vi.fn());
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));

const done = (overrides: Partial<SpeakingSessionDetail> = {}): SpeakingSessionDetail => ({
  id: "s1",
  conversation_id: "c1",
  scenario_id: "cafe",
  mode: "cascade",
  status: "done",
  level: "A2",
  turns: 8,
  spoken_turns: 6,
  spoken_seconds: 150,
  intelligibility: "mostly",
  started_at: "2026-10-10T09:00:00Z",
  ended_at: "2026-10-10T09:12:00Z",
  corrected_message_ids: [],
  summary: {
    went_well: ["You kept the conversation going."],
    mistakes: [{ quote: "I want buy a coffee", correction: "I want to buy a coffee.", explanation: "want + to + verb" }],
    more_natural: [{ quote: "Give me a latte", natural: "Could I have a latte, please?", note: "More polite." }],
    next_expressions: [
      { expression: "to go", meaning: "Not drinking it there." },
      { expression: "Could I have", meaning: "A polite way to ask." },
    ],
    intelligibility: "mostly",
  },
  ...overrides,
});

const onChange = vi.fn();

function show(detail: SpeakingSessionDetail) {
  return render(
    <NextIntlClientProvider locale="en" messages={en} timeZone="UTC">
      <SpeakingSummaryView detail={detail} scenario={null} onChange={onChange} />
    </NextIntlClientProvider>,
  );
}

beforeEach(() => {
  api.mockReset();
  push.mockReset();
  onChange.mockReset();
});

describe("SpeakingSummaryView", () => {
  it("shows the summary in its parts", () => {
    show(done());
    expect(screen.getByRole("heading", { name: "Free talk" })).toBeInTheDocument();
    expect(screen.getByText("8 turns")).toBeInTheDocument();
    expect(screen.getByText("spoke 2.5 min")).toBeInTheDocument();
    expect(screen.getByTestId("speaking-intelligibility")).toHaveTextContent("Mostly clear");
    expect(screen.getByTestId("summary-went-well")).toHaveTextContent("You kept the conversation going.");
    const mistakes = screen.getByTestId("summary-mistakes");
    expect(within(mistakes).getByText("I want buy a coffee")).toHaveClass("line-through");
    expect(mistakes).toHaveTextContent("I want to buy a coffee.");
    expect(screen.getByTestId("summary-more-natural")).toHaveTextContent("You said: Give me a latte");
  });

  it("shadows a fixed sentence, one at a time", async () => {
    show(done());
    const buttons = screen.getAllByTestId("shadowing-open");
    expect(buttons).toHaveLength(4);
    await userEvent.click(buttons[0]);
    expect(screen.getByTestId("shadowing-panel")).toHaveTextContent("speaking:s1:I want to buy a coffee.");
    await userEvent.click(buttons[1]);
    expect(screen.getAllByTestId("shadowing-panel")).toHaveLength(1);
    expect(screen.getByTestId("shadowing-panel")).toHaveTextContent("Could I have a latte, please?");
  });

  it("puts an expression on the word list, or says the dictionary has none", async () => {
    api.mockImplementation(async (_: string, init: { json: { word: string } }) => {
      if (init.json.word === "to go") return { added: true };
      throw new ApiError(404, "word_not_found", "the dictionary has no such word");
    });
    show(done());
    const next = screen.getByTestId("summary-next");
    const [first, second] = within(next).getAllByRole("button", { name: "Add to word list" });
    await userEvent.click(first);
    expect(await within(next).findByText("On your list")).toBeInTheDocument();
    await userEvent.click(second);
    expect(await within(next).findByText("Not in the dictionary")).toBeInTheDocument();
    expect(api).toHaveBeenCalledWith("/vocab/mine", { method: "POST", json: { word: "to go" } });
  });

  it("makes a failed summary again", async () => {
    api.mockResolvedValue(done());
    show(done({ status: "failed", summary: null, intelligibility: null }));
    expect(screen.getByText("The summary couldn't be made this time.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Try again/ }));
    expect(api).toHaveBeenCalledWith("/speaking/sessions/s1/end", { method: "POST" });
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ status: "done" }));
  });

  it("has nothing to sum up when nothing was said, and practises again", async () => {
    api.mockResolvedValue({ ...done(), id: "s2", status: "active" });
    show(done({ summary: null, turns: 0, intelligibility: null }));
    expect(screen.getByText(/nothing to sum up/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Practise again" }));
    expect(api).toHaveBeenCalledWith("/speaking/sessions", {
      method: "POST",
      json: { scenario_id: "cafe", locale: "en" },
    });
    expect(push).toHaveBeenCalledWith("/speaking/s2");
  });
});
