import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Advice } from "@/lib/advice";
import { ApiError } from "@/lib/api";
import type { ChatEvent } from "@/lib/sse";
import type { Conversation } from "@/lib/types";

import en from "../../../messages/en.json";
import { PlacementTutor, PlanStart, findPlanning } from "./placement-tutor";

const api = vi.hoisted(() => vi.fn());
const streamChat = vi.hoisted(() => vi.fn());
const streamOpening = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  api,
}));
vi.mock("@/lib/sse", () => ({ streamChat, streamOpening, OPENING_TURN_ID: "opening" }));

const FINISHED = "2026-10-01T08:00:00Z";
const conversation = (over: Partial<Conversation>): Conversation => ({
  id: "p1",
  title: "Study plan",
  created_at: "2026-10-01T08:05:00Z",
  updated_at: "2026-10-01T08:05:00Z",
  focus_kc: null,
  purpose: "planning",
  ...over,
});
const ready: Advice = {
  model_ready: true,
  items: [
    {
      candidate_id: "choose_book",
      kind: "choose_book",
      count: null,
      days_since: null,
      in_progress: false,
      kc: null,
      p_mastery: null,
      book: null,
    },
  ],
};

function wrap(node: React.ReactNode) {
  return render(
    <NextIntlClientProvider locale="en" messages={en} timeZone="UTC">
      {node}
    </NextIntlClientProvider>,
  );
}

async function* events(...items: ChatEvent[]) {
  yield* items;
}

const NO_ACTIVITY = { activities: [], memories: {}, kcs: {}, words_on_list: [], pending: false };

/** The backend by method and path; what the tutor did, and its cards, are empty. */
function backend(routes: Record<string, unknown>) {
  api.mockImplementation((path: string, init?: { method?: string }) => {
    const key = `${init?.method ?? "GET"} ${path.split("?")[0]}`;
    if (key in routes) {
      const value = routes[key];
      return value instanceof Error ? Promise.reject(value) : Promise.resolve(value);
    }
    if (key.endsWith("/activity")) return Promise.resolve(NO_ACTIVITY);
    if (key.endsWith("/cards")) return Promise.resolve({ cards: [] });
    return Promise.reject(new Error(`unexpected ${key}`));
  });
}

const posts = () => api.mock.calls.filter(([, init]) => init?.method === "POST");

beforeEach(() => {
  api.mockReset();
  streamChat.mockReset();
  streamOpening.mockReset();
});

/** A paragraph of a tutor message; its English words are separate spans (word popup). */
const tutorSays = (text: string) =>
  screen.findByText((_, el) => el?.tagName === "P" && el.textContent === text);

describe("findPlanning", () => {
  it("takes the latest planning conversation started since the test finished", async () => {
    backend({
      "GET /conversations": [
        conversation({ id: "old", created_at: "2026-09-01T00:00:00Z" }),
        conversation({ id: "daily", purpose: "daily", created_at: "2026-10-01T09:00:00Z" }),
        conversation({ id: "first", created_at: "2026-10-01T08:01:00Z" }),
        conversation({ id: "latest", created_at: "2026-10-01T08:30:00Z" }),
      ],
    });
    expect((await findPlanning(FINISHED))?.id).toBe("latest");
  });

  it("finds nothing for an older one, or without a finish time", async () => {
    backend({ "GET /conversations": [conversation({ created_at: "2026-09-01T00:00:00Z" })] });
    expect(await findPlanning(FINISHED)).toBeNull();
    expect(await findPlanning(null)).toBeNull();
  });
});

describe("PlanStart", () => {
  it("offers the talk, marked as AI", async () => {
    const onTalk = vi.fn();
    wrap(<PlanStart advice={ready} error={null} busy={false} onTalk={onTalk} />);
    expect(screen.getByTestId("ai-badge-plan_start")).toBeInTheDocument();
    await userEvent.click(
      screen.getByRole("button", { name: "Talk the result over with the tutor" }),
    );
    expect(onTalk).toHaveBeenCalled();
  });

  it("falls back to rule advice as links without a chat model", () => {
    wrap(
      <PlanStart advice={{ ...ready, model_ready: false }} error={null} busy={false} onTalk={vi.fn()} />,
    );
    expect(screen.queryByTestId("placement-plan")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open settings" })).toHaveAttribute(
      "href",
      "/settings",
    );
    expect(screen.getByTestId("advice-item")).toHaveTextContent("Choose a word book");
  });
});

describe("PlacementTutor", () => {
  it("creates the planning conversation and has the tutor open it, in the page", async () => {
    const created = conversation({});
    backend({
      "GET /conversations": [],
      "GET /advice": ready,
      "POST /conversations": created,
      "GET /conversations/p1/messages": [],
    });
    streamOpening.mockReturnValue(
      events(
        { event: "token", text: "Your level is B1. What is your goal?" },
        { event: "done", message_id: "a1", turn_id: "opening", usage: {} },
      ),
    );
    wrap(<PlacementTutor finishedAt={FINISHED} />);

    const talk = await screen.findByRole("button", { name: "Talk the result over with the tutor" });
    expect(posts()).toHaveLength(0); // nothing is created, and no model called, before this
    await userEvent.click(talk);

    expect(await tutorSays("Your level is B1. What is your goal?")).toBeInTheDocument();
    expect(posts()[0][1].json).toMatchObject({ purpose: "planning", locale: "en" });
    expect(streamOpening).toHaveBeenCalledTimes(1);
    expect(streamOpening.mock.calls[0][0]).toBe("p1");
    expect(screen.getByRole("link", { name: "Continue in chat" })).toHaveAttribute(
      "href",
      "/chat?c=p1",
    );
  });

  it("skips the opening when the learner types first", async () => {
    backend({
      "GET /conversations": [],
      "GET /advice": ready,
      "POST /conversations": conversation({}),
    });
    streamChat.mockReturnValue(
      events(
        { event: "token", text: "Let's pick a book." },
        { event: "done", message_id: "a1", turn_id: "u1", usage: {} },
      ),
    );
    wrap(<PlacementTutor finishedAt={FINISHED} />);
    await screen.findByTestId("placement-plan");

    await userEvent.type(screen.getByRole("textbox"), "Help me choose a book{Enter}");
    expect(await tutorSays("Let's pick a book.")).toBeInTheDocument();
    expect(streamChat.mock.calls[0].slice(0, 2)).toEqual(["p1", "Help me choose a book"]);
    expect(streamOpening).not.toHaveBeenCalled();
  });

  it("shows this test's planning conversation when the page is opened again", async () => {
    backend({
      "GET /conversations": [conversation({})],
      "GET /advice": ready,
      "GET /conversations/p1/messages": [
        { id: null, role: "assistant", content: "Your level is B1.", attachments: [] },
      ],
    });
    wrap(<PlacementTutor finishedAt={FINISHED} />);
    expect(await tutorSays("Your level is B1.")).toBeInTheDocument();
    expect(screen.queryByTestId("placement-plan")).not.toBeInTheDocument();
    expect(posts()).toHaveLength(0);
    expect(streamOpening).not.toHaveBeenCalled();
  });

  it("says why when the tutor can't open, and keeps the way in", async () => {
    backend({
      "GET /conversations": [conversation({})],
      "GET /advice": ready,
      "GET /conversations/p1/messages": [],
    });
    streamOpening.mockImplementation(() => {
      throw new ApiError(409, "no_llm_configured", "No chat model");
    });
    wrap(<PlacementTutor finishedAt={FINISHED} />);
    // An empty conversation from before isn't opened by itself.
    const talk = await screen.findByRole("button", { name: "Talk the result over with the tutor" });
    expect(streamOpening).not.toHaveBeenCalled();
    await userEvent.click(talk);
    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    expect(screen.getByRole("link", { name: "Go to Settings" })).toHaveAttribute(
      "href",
      "/settings",
    );
    expect(screen.getByTestId("placement-plan")).toBeEnabled();
  });
});
