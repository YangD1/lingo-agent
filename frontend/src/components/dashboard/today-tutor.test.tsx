import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { type Advice, type AdviceItem, templateKey } from "@/lib/advice";
import type { ChatEvent } from "@/lib/sse";

import en from "../../../messages/en.json";
import zh from "../../../messages/zh-CN.json";
import { TodayStart, TodayTutor } from "./today-tutor";

const api = vi.hoisted(() => vi.fn());
const streamChat = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  api,
}));
vi.mock("@/lib/sse", () => ({ streamChat, streamOpening: vi.fn(), OPENING_TURN_ID: "opening" }));

const item = (over: Partial<AdviceItem>): AdviceItem => ({
  candidate_id: over.kind ?? "vocab_review",
  kind: "vocab_review",
  count: null,
  days_since: null,
  in_progress: false,
  kc: null,
  p_mastery: null,
  book: null,
  ...over,
});

const KC = { id: "g.third", name_en: "Third person -s", name_zh: "第三人称单数", cefr: "A1" } as const;
const TODAY = {
  id: "d1",
  title: "Today · Oct 1",
  created_at: "",
  updated_at: "",
  focus_kc: null,
  purpose: "daily" as const,
};

function wrap(node: React.ReactNode, locale: "en" | "zh-CN" = "en") {
  return render(
    <NextIntlClientProvider locale={locale} messages={locale === "en" ? en : zh} timeZone="UTC">
      {node}
    </NextIntlClientProvider>,
  );
}

function start(advice: Advice | null, locale: "en" | "zh-CN" = "en", busy = false) {
  const actions = { send: vi.fn().mockResolvedValue(true), open: vi.fn(), busy };
  wrap(<TodayStart advice={advice} error={null} actions={actions} />, locale);
  return actions;
}

async function* events(...items: ChatEvent[]) {
  yield* items;
}

const NO_ACTIVITY = { activities: [], memories: {}, kcs: {}, words_on_list: [], pending: false };

/** The backend by path; what the tutor did, and its cards, are empty. */
function backend(routes: Record<string, unknown>) {
  api.mockImplementation((path: string) => {
    const bare = path.split("?")[0];
    if (bare in routes) return Promise.resolve(routes[bare]);
    if (bare.endsWith("/activity")) return Promise.resolve(NO_ACTIVITY);
    if (bare.endsWith("/cards")) return Promise.resolve({ cards: [] });
    return Promise.reject(new Error(`unexpected ${path}`));
  });
}

beforeEach(() => {
  api.mockReset();
  streamChat.mockReset();
});

/** A paragraph of a tutor message; its English words are separate spans (word popup). */
const tutorSays = (text: string) =>
  screen.findByText((_, el) => el?.tagName === "P" && el.textContent === text);

describe("templateKey", () => {
  it("tells a first test, a retest and one left halfway apart", () => {
    expect(templateKey(item({ kind: "placement" }))).toBe("placement");
    expect(templateKey(item({ kind: "placement", days_since: 70 }))).toBe("retest");
    expect(templateKey(item({ kind: "placement", days_since: 70, in_progress: true }))).toBe(
      "resume",
    );
    expect(templateKey(item({ kind: "vocab_learn" }))).toBe("vocab_learn");
  });
});

describe("TodayStart", () => {
  const ready: Advice = {
    model_ready: true,
    items: [
      item({ kind: "vocab_review", count: 12 }),
      item({ kind: "grammar_practice", candidate_id: "grammar_practice:g.third", kc: KC }),
      item({ kind: "placement", days_since: 75 }),
      item({ kind: "choose_book" }),
    ],
  };

  it("greets by the top candidate and offers quick replies from the top three", async () => {
    const actions = start(ready);
    expect(screen.getByTestId("today-greeting")).toHaveTextContent(
      "You have 12 words due today.",
    );
    const replies = within(screen.getByTestId("today-quick"))
      .getAllByRole("button")
      .filter((b) => !b.dataset.testid?.startsWith("ai-badge"));
    expect(replies.map((b) => b.textContent)).toEqual([
      "What should I study today?",
      "Help me review the 12 words that are due",
      "I'd like to practise Third person -s",
      "I'd like to retest my level",
    ]);
    // A quick reply is the learner saying it: a normal chat turn.
    expect(screen.getByTestId("ai-badge-chat_message")).toBeInTheDocument();

    await userEvent.click(replies[2]);
    expect(actions.send).toHaveBeenCalledWith("I'd like to practise Third person -s");
  });

  it("holds the quick replies while a turn is on its way", () => {
    start(ready, "en", true);
    expect(screen.getByRole("button", { name: "What should I study today?" })).toBeDisabled();
  });

  it("greets in Chinese, and has one quick reply when nothing is pending", () => {
    start({ model_ready: true, items: [] }, "zh-CN");
    expect(screen.getByTestId("today-greeting")).toHaveTextContent("今天没有特别要补的");
    expect(screen.getByRole("button", { name: "今天学什么？" })).toBeInTheDocument();
  });

  it("falls back to rule advice as links without a chat model", () => {
    const actions = start({ ...ready, model_ready: false });
    expect(screen.queryByTestId("today-quick")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open settings" })).toHaveAttribute(
      "href",
      "/settings",
    );
    const items = screen.getAllByTestId("advice-item");
    expect(items.map((i) => i.dataset.kind)).toEqual([
      "vocab_review",
      "grammar_practice",
      "placement",
      "choose_book",
    ]);
    expect(items[0]).toHaveTextContent("12 due");
    expect(within(items[0]).getByRole("link", { name: "Review" })).toHaveAttribute(
      "href",
      "/vocab/review",
    );
    expect(within(items[1]).getByRole("link", { name: "Practise with questions" })).toHaveAttribute(
      "href",
      "/practice?from=dashboard&kc=g.third",
    );
    expect(within(items[1]).getByRole("link", { name: "Practise in conversation" })).toHaveAttribute(
      "href",
      "/chat?practice=g.third",
    );
    expect(within(items[1]).getByRole("link", { name: "See the evidence" })).toHaveAttribute(
      "href",
      "/learner?kc=g.third",
    );
    expect(items[2]).toHaveTextContent("Last taken 75 days ago");
    expect(actions.send).not.toHaveBeenCalled();
  });
});

describe("TodayTutor", () => {
  const advice: Advice = { model_ready: true, items: [item({ kind: "vocab_review", count: 3 })] };

  it("shows today's conversation when there is one, with a way to the chat page", async () => {
    backend({
      "/conversations/today": TODAY,
      "/advice": advice,
      "/conversations/d1/messages": [
        { id: "u1", role: "user", content: "What should I study today?", attachments: [] },
        { id: "a1", role: "assistant", content: "Let's review your 3 words.", attachments: [] },
      ],
    });
    wrap(<TodayTutor />);
    expect(await tutorSays("Let's review your 3 words.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Continue in chat" })).toHaveAttribute(
      "href",
      "/chat?c=d1",
    );
    expect(screen.queryByTestId("today-greeting")).not.toBeInTheDocument();
  });

  it("creates today's conversation with the first quick reply, not before", async () => {
    backend({ "/conversations/today": null, "/advice": advice, "/conversations": TODAY });
    streamChat.mockReturnValue(
      events(
        { event: "token", text: "Sure." },
        { event: "done", message_id: "a1", turn_id: "u1", usage: {} },
      ),
    );
    const onTurnFinished = vi.fn();
    wrap(<TodayTutor onTurnFinished={onTurnFinished} />);

    const reply = await screen.findByRole("button", {
      name: "Help me review the 3 words that are due",
    });
    expect(api.mock.calls.some(([, init]) => init?.method === "POST")).toBe(false);
    await userEvent.click(reply);

    expect(await tutorSays("Sure.")).toBeInTheDocument();
    const post = api.mock.calls.find(([, init]) => init?.method === "POST");
    expect(post?.[0]).toBe("/conversations");
    expect(post?.[1].json).toMatchObject({ purpose: "daily", locale: "en" });
    expect(streamChat.mock.calls[0].slice(0, 2)).toEqual([
      "d1",
      "Help me review the 3 words that are due",
    ]);
    expect(screen.getByRole("link", { name: "Continue in chat" })).toHaveAttribute(
      "href",
      "/chat?c=d1",
    );
    await waitFor(() => expect(onTurnFinished).toHaveBeenCalled());
  });
});
