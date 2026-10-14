import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import Link from "next/link";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Conversation } from "@/lib/types";

import en from "../../../messages/en.json";
import { PetChat, resetPetChat } from "./pet-chat";

const api = vi.hoisted(() => vi.fn());
// Where each message went: the pet took it, or it went to the tutor.
const sent = vi.hoisted(() => [] as string[]);
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  api,
}));

// The conversation panel has its own tests: here, which conversation and what it sends.
vi.mock("@/components/chat/tutor-panel", () => ({
  TutorPanel: ({
    conversationId,
    onConversationCreated,
    createConversation,
    autoOpen,
    empty,
    autoFocus,
    initialText,
    beforeSend,
  }: {
    conversationId: string | null;
    onConversationCreated: (c: Conversation) => void;
    createConversation?: () => Promise<Conversation>;
    autoOpen?: boolean;
    empty?: (actions: { send: () => void; open: () => void; busy: boolean }) => React.ReactNode;
    autoFocus?: boolean;
    initialText?: string;
    beforeSend?: (text: string, attachments: unknown[]) => boolean;
  }) => (
    <div
      data-testid="panel"
      data-conversation={conversationId ?? "new"}
      data-auto-open={autoOpen || undefined}
      data-creates={createConversation ? "today" : "plain"}
      data-autofocus={autoFocus || undefined}
    >
      {empty && <div data-testid="panel-empty">{empty({ send: () => {}, open: () => {}, busy: false })}</div>}
      <textarea aria-label="Message" defaultValue={initialText} />
      <button
        onClick={(e) => {
          const box = e.currentTarget.parentElement!.querySelector("textarea")!;
          sent.push(beforeSend?.(box.value, []) ? `pet:${box.value}` : `tutor:${box.value}`);
        }}
      >
        send
      </button>
      <button onClick={() => onConversationCreated(conversation("c9", "Fresh"))}>create</button>
      <Link href="/writing" onClick={(e) => e.preventDefault()}>
        card link
      </Link>
      <a href="https://example.com/" onClick={(e) => e.preventDefault()}>
        outside link
      </a>
    </div>
  ),
}));

/** The backend: today's conversation (null: none yet), and the one creating it returns. */
function serve({ today = null as Conversation | null, fail = false } = {}) {
  api.mockImplementation(async (path: string, init?: { method?: string; json?: unknown }) => {
    if (fail) throw new Error("offline");
    if (path.startsWith("/conversations/today")) return today;
    if (path === "/conversations" && init?.method === "POST") {
      return conversation("t1", "Today's study", { purpose: "daily" });
    }
    if (path === "/conversations") return today ? [today] : [];
    throw new Error(`unexpected ${path}`);
  });
}

const posts = () => api.mock.calls.filter(([, init]) => init?.method === "POST");

const conversation = (id: string, title = "", extra: Partial<Conversation> = {}): Conversation => ({
  id,
  title,
  created_at: "",
  updated_at: "",
  focus_kc: null,
  purpose: null,
  article_id: null,
  ...extra,
});

function show(onClose = vi.fn(), extra: Partial<Parameters<typeof PetChat>[0]> = {}) {
  render(
    <NextIntlClientProvider locale="en" messages={en} timeZone="UTC">
      <PetChat name="Max" side="right" onClose={onClose} {...extra} />
    </NextIntlClientProvider>,
  );
  return onClose;
}

beforeEach(() => {
  sent.length = 0;
  api.mockReset();
  resetPetChat();
});

describe("PetChat", () => {
  it("opens on today's conversation, ready to type (ADR 0041)", async () => {
    serve({ today: conversation("c2", "Today's study", { purpose: "daily" }) });
    show();
    const panel = await screen.findByTestId("panel");
    expect(panel).toHaveAttribute("data-conversation", "c2");
    expect(screen.getByRole("heading", { name: "Today's study" })).toBeInTheDocument();
    // The panel focuses its input box once the history is in.
    expect(panel).toHaveAttribute("data-autofocus", "true");
    // It opens only while empty: the panel knows once it has loaded the history.
    expect(panel).toHaveAttribute("data-auto-open", "true");
    expect(screen.getByTestId("pet-chat-open-in-chat")).toHaveAttribute("href", "/chat?c=c2");
    expect(posts()).toEqual([]);
  });

  it("the first time in a day, creates today's conversation for the tutor to open", async () => {
    serve();
    show();
    const panel = await screen.findByTestId("panel");
    expect(panel).toHaveAttribute("data-conversation", "t1");
    expect(panel).toHaveAttribute("data-auto-open", "true");
    expect(posts()).toEqual([
      ["/conversations", expect.objectContaining({ json: expect.objectContaining({ purpose: "daily" }) })],
    ]);
  });

  it("with the opening switched off, waits for the learner's first message", async () => {
    serve();
    show(vi.fn(), {
      dailyOpening: false,
      advice: { items: [], model_ready: true, reminder: null } as never,
    });
    const panel = await screen.findByTestId("panel");
    expect(panel).toHaveAttribute("data-conversation", "new");
    expect(panel).not.toHaveAttribute("data-auto-open");
    // Today's, created with the first message; the dashboard's greeting until then.
    expect(panel).toHaveAttribute("data-creates", "today");
    expect(screen.getByTestId("today-greeting")).toBeInTheDocument();
    expect(posts()).toEqual([]);
  });

  it("without a model, neither opens nor creates anything", async () => {
    serve();
    show(vi.fn(), { modelReady: false });
    const panel = await screen.findByTestId("panel");
    expect(panel).toHaveAttribute("data-conversation", "new");
    expect(panel).not.toHaveAttribute("data-auto-open");
    expect(screen.queryByTestId("panel-empty")).toBeNull();
    expect(posts()).toEqual([]);
  });

  it("starts a new chat, and goes on with it until the page is reloaded", async () => {
    serve({ today: conversation("c2", "Today's study", { purpose: "daily" }) });
    show();
    await screen.findByTestId("panel");
    await userEvent.click(screen.getByRole("button", { name: "New chat" }));
    const panel = screen.getByTestId("panel");
    expect(panel).toHaveAttribute("data-conversation", "new");
    expect(panel).toHaveAttribute("data-creates", "plain");
    expect(panel).not.toHaveAttribute("data-auto-open");
    expect(screen.getByRole("button", { name: "New chat" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "create" }));
    expect(screen.getByTestId("panel")).toHaveAttribute("data-conversation", "c9");

    // Closed and opened again: the same chat, today's isn't looked up.
    cleanup();
    api.mockClear();
    show();
    expect(await screen.findByTestId("panel")).toHaveAttribute("data-conversation", "c9");
    expect(api).not.toHaveBeenCalledWith(expect.stringMatching(/^\/conversations\/today/));

    // Reloaded: today's again.
    cleanup();
    resetPetChat();
    show();
    await waitFor(() =>
      expect(screen.getByTestId("panel")).toHaveAttribute("data-conversation", "c2"),
    );
  });

  it("closes with Escape, the close button, or going to the chat page", async () => {
    serve({ today: conversation("c2") });
    const onClose = show();
    await screen.findByTestId("panel");
    await userEvent.keyboard("{Escape}");
    await userEvent.click(screen.getByRole("button", { name: "Close" }));
    await userEvent.click(screen.getByTestId("pet-chat-open-in-chat"));
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(3));
  });

  it("makes way when a card's link leads elsewhere in the app (ADR 0039)", async () => {
    serve({ today: conversation("c2") });
    const onClose = show();
    await screen.findByTestId("panel");
    await userEvent.click(screen.getByRole("link", { name: "outside link" }));
    expect(onClose).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("link", { name: "card link" }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("offers shortcuts, and the way to set up a model when there is none (ADR 0039)", async () => {
    serve();
    show(vi.fn(), { modelReady: false });
    await screen.findByTestId("panel");
    const shortcuts = screen.getByRole("navigation", { name: "I can open these for you:" });
    expect(within(shortcuts).getByRole("link", { name: "Flashcards" })).toHaveAttribute(
      "href",
      "/vocab/review",
    );
    expect(screen.getByTestId("pet-chat-no-model")).toHaveTextContent("No chat model is set up");
    expect(screen.getByRole("link", { name: "Set up models" })).toHaveAttribute(
      "href",
      "/settings#connections",
    );
  });

  it("hands a short command to the pet, not the tutor", async () => {
    serve();
    const onCommand = vi.fn();
    show(vi.fn(), { onCommand });
    await screen.findByTestId("panel");
    expect(screen.queryByTestId("pet-chat-no-model")).toBeNull();
    const box = screen.getByRole("textbox", { name: "Message" });
    await userEvent.type(box, "flashcards");
    await userEvent.click(screen.getByRole("button", { name: "send" }));
    await userEvent.clear(box);
    await userEvent.type(box, "how should I review words?");
    await userEvent.click(screen.getByRole("button", { name: "send" }));
    expect(sent).toEqual(["pet:flashcards", "tutor:how should I review words?"]);
    expect(onCommand).toHaveBeenCalledWith(expect.objectContaining({ id: "vocab_review" }), "flashcards");
  });

  it("sends a command it was asked to ask the tutor as it is", async () => {
    serve();
    show(vi.fn(), { onCommand: vi.fn(), draft: "flashcards" });
    await screen.findByTestId("panel");
    expect(screen.getByRole("textbox", { name: "Message" })).toHaveValue("flashcards");
    await userEvent.click(screen.getByRole("button", { name: "send" }));
    expect(sent).toEqual(["tutor:flashcards"]);
  });

  it("without the backend, starts with nothing", async () => {
    serve({ fail: true });
    show();
    expect(await screen.findByTestId("panel")).toHaveAttribute("data-conversation", "new");
  });
});
