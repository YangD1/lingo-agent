import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import Link from "next/link";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Conversation } from "@/lib/types";

import en from "../../../messages/en.json";
import { PetChat, resetPetChat } from "./pet-chat";

const api = vi.hoisted(() => vi.fn());
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
  }: {
    conversationId: string | null;
    sendFeature?: string;
    onConversationCreated: (c: Conversation) => void;
    autoFocus?: boolean;
  }) => (
    <div
      data-testid="panel"
      data-conversation={conversationId ?? "new"}
      data-feature={sendFeature ?? ""}
      data-autofocus={autoFocus || undefined}
    >
      <textarea aria-label="Message" />
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

function show(onClose = vi.fn()) {
  render(
    <NextIntlClientProvider locale="en" messages={en} timeZone="UTC">
      <PetChat name="Max" side="right" onClose={onClose} />
    </NextIntlClientProvider>,
  );
  return onClose;
}

beforeEach(() => {
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

  it("without the list, starts a new chat", async () => {
    api.mockRejectedValue(new Error("offline"));
    show();
    expect(await screen.findByTestId("panel")).toHaveAttribute("data-conversation", "new");
  });
});
