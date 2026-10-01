"use client";

import { useTranslations } from "next-intl";
import { type ReactNode, useEffect, useRef } from "react";

import { useErrorMessage } from "@/i18n/errors";
import { cn } from "@/lib/utils";

import { Markdown } from "./markdown";
import { MessageAttachments } from "./message-attachments";
import { TurnActivity } from "./turn-activity";
import { TutorCards } from "./tutor-cards";
import type { ActivityView } from "./use-activity";
import type { CardsView } from "./use-cards";
import type { ChatMessage } from "./use-chat-session";
import { WordPopup } from "./word-popup";

export function MessageList({
  messages,
  activity,
  cards,
  empty,
}: {
  messages: ChatMessage[];
  /** What the tutor did per turn; absent when the learner hid it. */
  activity?: ActivityView;
  /** Cards the tutor showed per turn (ADR 0015); part of the conversation, never hidden. */
  cards?: CardsView;
  /** Shown instead of the default hint while there are no messages. */
  empty?: ReactNode;
}) {
  const t = useTranslations("chat");
  const errorMessage = useErrorMessage();
  const scrollRef = useRef<HTMLDivElement>(null);
  const listRef = useRef<HTMLOListElement>(null);

  // Scroll the list itself, not the page: embedded in the dashboard, the page stays put.
  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages]);

  if (messages.length === 0) {
    return (
      empty ?? (
        <div className="flex flex-1 items-center justify-center p-8 text-center text-muted-foreground">
          {t("empty")}
        </div>
      )
    );
  }

  return (
    <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto">
      <ol
        ref={listRef}
        className="mx-auto flex max-w-3xl flex-col gap-4 p-4"
        aria-label={t("messages")}
      >
        {messages.map((m) => (
          <li
            key={m.key}
            data-role={m.role}
            data-status={m.status}
            className={cn("flex max-w-[85%] flex-col", m.role === "user" ? "self-end" : "self-start")}
          >
            {/* The message itself; what the tutor did goes below it, outside the bubble. */}
            <div
              data-slot="message"
              className={cn(
                "rounded-lg px-4 py-2",
                m.role === "user"
                  ? "bg-primary whitespace-pre-wrap text-primary-foreground"
                  : "bg-muted",
              )}
            >
              {m.attachments && m.attachments.length > 0 && (
                <MessageAttachments attachments={m.attachments} />
              )}
              {!m.content ? (
                m.status === "streaming" && <span className="animate-pulse">…</span>
              ) : m.role === "assistant" ? (
                <Markdown words>{m.content}</Markdown>
              ) : (
                m.content
              )}
              {m.status === "stopped" && (
                <p className="mt-1 text-xs text-muted-foreground">{t("stopped")}</p>
              )}
              {m.status === "error" && m.error && (
                <p role="alert" className="mt-1 text-xs text-destructive">
                  {errorMessage(m.error)}
                </p>
              )}
            </div>
            {cards && m.role === "assistant" && m.turnId && (
              <TutorCards cards={cards.byTurn[m.turnId] ?? []} onDecide={cards.decide} />
            )}
            {activity && m.role === "assistant" && m.turnId && m.status !== "streaming" && (
              <TurnActivity
                activities={activity.byTurn[m.turnId] ?? []}
                memories={activity.memories}
                kcs={activity.kcs}
                wordsOnList={activity.wordsOnList}
                onRemoveWord={activity.removeWord}
                waiting={activity.waiting.has(m.turnId)}
              />
            )}
          </li>
        ))}
      </ol>
      <WordPopup container={listRef} />
    </div>
  );
}
