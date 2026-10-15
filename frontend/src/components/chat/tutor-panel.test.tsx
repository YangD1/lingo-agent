import { render, screen, waitFor } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { TutorCard } from "@/lib/cards";

import en from "../../../messages/en.json";
import { TutorPanel } from "./tutor-panel";

const api = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  api,
}));
const streamOpening = vi.hoisted(() => vi.fn());
vi.mock("@/lib/sse", () => ({ streamChat: vi.fn(), streamOpening, OPENING_TURN_ID: "opening" }));
vi.mock("@/lib/ai-usage", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/ai-usage")>()),
  loadEstimates: () => new Promise(() => {}),
}));

const NO_ACTIVITY = { activities: [], memories: {}, kcs: {}, words_on_list: [], pending: false };

const quiz = (turn_id: string): TutorCard => ({
  id: "q1",
  turn_id,
  kind: "quiz",
  params: { set_id: 7, kc_id: "g.third", purpose: "quiz" },
  status: "info",
  display: {},
  created_at: null,
  decided_at: null,
  undone_at: null,
});

/** An empty conversation, with these cards; a quiz set that never arrives. */
function backend(cards: TutorCard[]) {
  api.mockImplementation((path: string) => {
    const bare = path.split("?")[0];
    if (bare.endsWith("/messages")) return Promise.resolve([]);
    if (bare.endsWith("/activity")) return Promise.resolve(NO_ACTIVITY);
    if (bare.endsWith("/cards")) return Promise.resolve({ cards });
    if (bare.endsWith("/attachments")) return Promise.resolve([]);
    return new Promise(() => {});
  });
}

async function* nothing() {}

function show() {
  return render(
    <NextIntlClientProvider locale="en" messages={en} timeZone="UTC">
      <TutorPanel conversationId="c1" onConversationCreated={() => {}} autoOpen />
    </NextIntlClientProvider>,
  );
}

beforeEach(() => {
  api.mockReset();
  streamOpening.mockReset().mockImplementation(nothing);
});

describe("TutorPanel opening", () => {
  it("has the tutor speak first into an empty conversation", async () => {
    backend([]);
    show();
    await waitFor(() => expect(streamOpening).toHaveBeenCalledOnce());
    expect(streamOpening.mock.calls[0][0]).toBe("c1");
  });

  it("does not open a lesson tested out of: its quiz card is shown instead (ADR 0044 §5)", async () => {
    backend([quiz("test-out-20261015T120000000000")]);
    show();
    expect(await screen.findByTestId("quiz-card")).toBeInTheDocument();
    await new Promise((r) => setTimeout(r, 20));
    expect(streamOpening).not.toHaveBeenCalled();
  });
});
