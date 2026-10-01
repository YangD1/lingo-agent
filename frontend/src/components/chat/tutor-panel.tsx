"use client";

import { useTranslations } from "next-intl";
import Link from "next/link";
import { type DragEvent, type ReactNode, useEffect, useRef, useState } from "react";

import { buttonVariants } from "@/components/ui/button";
import { type ApiErrorLike, useErrorMessage } from "@/i18n/errors";
import { useShowActivity } from "@/lib/preferences";
import type { Attachment, Conversation } from "@/lib/types";
import { cn } from "@/lib/utils";

import { SETTINGS_ERRORS } from "./attachment-tray";
import { Composer } from "./composer";
import { LanguageSwitch } from "./language-switch";
import { MessageList } from "./message-list";
import { useActivity } from "./use-activity";
import { useAttachments } from "./use-attachments";
import { useCards } from "./use-cards";
import { useChatSession } from "./use-chat-session";

/** What an empty conversation's placeholder can do: say something, or have the tutor open. */
export type EmptyActions = {
  send: (text: string, attachments?: Attachment[]) => Promise<boolean>;
  open: () => Promise<void>;
  /** A turn is streaming or the history is loading: hold off. */
  busy: boolean;
};

type Props = {
  /** Null: a new chat, created with the first message or upload. */
  conversationId: string | null;
  onConversationCreated: (conversation: Conversation) => void;
  /** After a reply finishes (the backend retitled or bumped the conversation). */
  onTurnFinished?: () => void;
  /** How the conversation is created; a plain one by default. */
  createConversation?: () => Promise<Conversation>;
  /** See useChatSession: false when `createConversation` may return an existing one. */
  discardRefused?: boolean;
  /** Have the tutor speak first while the conversation is empty (practice, planning). */
  autoOpen?: boolean;
  /** Above the messages: the practice bar or the placement banner. */
  header?: ReactNode;
  /** Instead of the default hint while there are no messages. */
  empty?: (actions: EmptyActions) => ReactNode;
  /** An error from outside the panel, e.g. starting the conversation failed. */
  error?: ApiErrorLike | null;
  className?: string;
};

/**
 * One conversation with the tutor: messages, cards, what the tutor did, and the full input
 * box with attachments and recording (ADR 0016 §5). The chat page puts it next to the
 * conversation list; the dashboard embeds it at a fixed height.
 */
export function TutorPanel({
  conversationId,
  onConversationCreated,
  onTurnFinished,
  createConversation,
  discardRefused,
  autoOpen = false,
  header,
  empty,
  error: outerError = null,
  className,
}: Props) {
  const t = useTranslations("chat");
  const errorMessage = useErrorMessage();
  const [showActivity] = useShowActivity();
  const activity = useActivity(conversationId, showActivity);
  const cards = useCards(conversationId);
  const session = useChatSession(conversationId, {
    onConversationCreated,
    onTurnFinished: () => {
      onTurnFinished?.();
      cards.reload(); // current statuses, and live numbers for link cards
    },
    onActivity: activity.addLive,
    onCard: cards.add,
    onReplyDone: activity.turnFinished,
    createConversation,
    discardRefused,
  });
  const tray = useAttachments(conversationId, session.ensureConversation);

  // The tutor speaks first (Q19a, ADR 0015 §6). Tried once per conversation and page load,
  // so a refusal (e.g. no model) doesn't loop.
  const opened = useRef(new Set<string>());
  const { readyFor, messages, streaming, open } = session;
  useEffect(() => {
    if (!autoOpen || !conversationId || readyFor !== conversationId) return;
    if (opened.current.has(conversationId) || messages.length > 0 || streaming) return;
    opened.current.add(conversationId);
    void open();
  }, [autoOpen, conversationId, readyFor, messages.length, streaming, open]);

  const [dragging, setDragging] = useState(false);
  const hasFiles = (event: DragEvent) => event.dataTransfer.types.includes("Files");
  function onDrop(event: DragEvent) {
    if (!hasFiles(event)) return;
    event.preventDefault();
    setDragging(false);
    if (!session.loading) tray.add(Array.from(event.dataTransfer.files));
  }

  const error = session.error ?? outerError;
  return (
    <section
      className={cn("relative flex min-w-0 flex-col", className)}
      onDragOver={(e) => {
        if (!hasFiles(e)) return;
        e.preventDefault();
        setDragging(true);
      }}
      onDragLeave={(e) => {
        // Only when leaving the section itself, not moving between its children.
        if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setDragging(false);
      }}
      onDrop={onDrop}
    >
      {dragging && (
        <div className="pointer-events-none absolute inset-2 z-10 flex items-center justify-center rounded-xl border-2 border-dashed border-primary bg-background/80 text-sm font-medium">
          {t("attachments.dropHere")}
        </div>
      )}
      {header}
      <MessageList
        messages={session.messages}
        activity={showActivity ? activity : undefined}
        cards={cards}
        empty={empty?.({
          send: session.send,
          open: session.open,
          busy: session.streaming || session.loading,
        })}
      />
      {error && (
        <div
          role="alert"
          className="mx-auto flex w-full max-w-3xl items-center gap-3 px-4 text-sm text-destructive"
        >
          <span>{errorMessage(error)}</span>
          {SETTINGS_ERRORS.has(error.code) && (
            <Link href="/settings" className={buttonVariants({ size: "sm", variant: "outline" })}>
              {t("goToSettings")}
            </Link>
          )}
        </div>
      )}
      <Composer
        streaming={session.streaming}
        disabled={session.loading}
        tray={tray}
        onSend={session.send}
        onStop={session.stop}
        toolbar={<LanguageSwitch />}
      />
    </section>
  );
}
