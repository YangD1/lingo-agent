import { render, screen, waitFor, within } from "@testing-library/react";
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
    sendFeature,
    onConversationCreated,
    autoFocus,
    initialText,
    beforeSend,
  }: {
    conversationId: string | null;
    sendFeature?: string;
    onConversationCreated: (c: Conversation) => void;
    autoFocus?: boolean;
    initialText?: string;
    beforeSend?: (text: string, attachments: unknown[]) => boolean;
  }) => (
    <div
      data-testid="panel"
      data-conversation={conversationId ?? "new"}
      data-feature={sendFeature ?? ""}
      data-autofocus={autoFocus || undefined}
    >
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
  it("goes on with the latest conversation, ready to type", async () => {
    api.mockResolvedValue([conversation("c2", "Weekend plans"), conversation("c1")]);
    show();
    const panel = await screen.findByTestId("panel");
    expect(panel).toHaveAttribute("data-conversation", "c2");
    expect(screen.getByRole("heading", { name: "Weekend plans" })).toBeInTheDocument();
    // The panel focuses its input box once the history is in.
    expect(panel).toHaveAttribute("data-autofocus", "true");
    expect(screen.getByTestId("pet-chat-open-in-chat")).toHaveAttribute("href", "/chat?c=c2");
  });

  it("starts a new chat without any, and keeps it for next time", async () => {
    api.mockResolvedValue([]);
    show();
    const panel = await screen.findByTestId("panel");
    expect(panel).toHaveAttribute("data-conversation", "new");
    expect(screen.getByTestId("pet-chat-open-in-chat")).toHaveAttribute("href", "/chat");
    await userEvent.click(screen.getByRole("button", { name: "create" }));
    expect(panel).toHaveAttribute("data-conversation", "c9");
  });

  it("a reading conversation sends as reading help", async () => {
    api.mockResolvedValue([conversation("c3", "", { article_id: 7 })]);
    show();
    expect(await screen.findByTestId("panel")).toHaveAttribute("data-feature", "reading_coach");
  });

  it("closes with Escape, the close button, or going to the chat page", async () => {
    api.mockResolvedValue([conversation("c2")]);
    const onClose = show();
    await screen.findByTestId("panel");
    await userEvent.keyboard("{Escape}");
    await userEvent.click(screen.getByRole("button", { name: "Close" }));
    await userEvent.click(screen.getByTestId("pet-chat-open-in-chat"));
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(3));
  });

  it("makes way when a card's link leads elsewhere in the app (ADR 0039)", async () => {
    api.mockResolvedValue([conversation("c2")]);
    const onClose = show();
    await screen.findByTestId("panel");
    await userEvent.click(screen.getByRole("link", { name: "outside link" }));
    expect(onClose).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("link", { name: "card link" }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("offers shortcuts, and the way to set up a model when there is none (ADR 0039)", async () => {
    api.mockResolvedValue([]);
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
    api.mockResolvedValue([]);
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
    api.mockResolvedValue([]);
    show(vi.fn(), { onCommand: vi.fn(), draft: "flashcards" });
    await screen.findByTestId("panel");
    expect(screen.getByRole("textbox", { name: "Message" })).toHaveValue("flashcards");
    await userEvent.click(screen.getByRole("button", { name: "send" }));
    expect(sent).toEqual(["tutor:flashcards"]);
  });

  it("without the list, starts a new chat", async () => {
    api.mockRejectedValue(new Error("offline"));
    show();
    expect(await screen.findByTestId("panel")).toHaveAttribute("data-conversation", "new");
  });
});
