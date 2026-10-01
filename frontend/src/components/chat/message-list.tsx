"use client";

import { useTranslations } from "next-intl";
import { type ReactNode, useEffect, useRef } from "react";

import { LogoMark } from "@/components/brand/logo";
import { useErrorMessage } from "@/i18n/errors";
import { stopSpeaking } from "@/lib/speech";

import { Markdown } from "./markdown";
import { MessageAttachments } from "./message-attachments";
import { ReplyTools, useReplyTranslations } from "./reply-tools";
import { TurnActivity } from "./turn-activity";
import { TutorCards } from "./tutor-cards";
import type { ActivityView } from "./use-activity";
import type { CardsView } from "./use-cards";
import type { ChatMessage } from "./use-chat-session";
import { WordPopup } from "./word-popup";

export function MessageList({
  conversationId = null,
  messages,
  activity,
  cards,
  empty,
}: {
  /** Where the messages are saved; needed to translate the tutor's. */
  conversationId?: string | null;
  messages: ChatMessage[];
  /** What the tutor did per turn; absent when the learner hid it. */
  activity?: ActivityView;
  /** Cards the tutor showed per turn (ADR 0015); part of the conversation, never hidden. */
  cards?: CardsView;
  /** Shown instead of the default hint while there are no messages. */
  empty?: ReactNode;
}) {
  const t = useTranslations("chat");
  const scrollRef = useRef<HTMLDivElement>(null);
  const listRef = useRef<HTMLOListElement>(null);
  const translations = useReplyTranslations(conversationId);

  // Reading aloud stops with the conversation it reads from.
  useEffect(() => stopSpeaking, [conversationId]);

  // Scroll the list itself, not the page: embedded in the dashboard, the page stays put.
  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages]);

  if (messages.length === 0) {
    return (
      empty ?? (
        <div className="flex flex-1 items-center justify-center p-6">
          <div className="flex max-w-sm flex-col items-center gap-3 rounded-xl border border-dashed px-6 py-8 text-center text-sm text-muted-foreground">
            <LogoMark className="size-8" />
            {t("empty")}
          </div>
        </div>
      )
    );
  }

  return (
    <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto">
      <ol
        ref={listRef}
        className="mx-auto flex max-w-3xl flex-col gap-[22px] px-3 py-5 md:px-8"
        aria-label={t("messages")}
      >
        {messages.map((m) =>
          m.role === "user" ? (
            <li
              key={m.key}
              data-role={m.role}
              data-status={m.status}
              className="flex max-w-[86%] flex-col self-end md:max-w-[78%]"
            >
              <div
                data-slot="message"
                className="rounded-[18px_18px_6px_18px] bg-primary px-[15px] py-2.5 text-[15.5px] leading-[1.6] whitespace-pre-wrap text-primary-foreground"
              >
                {m.attachments && m.attachments.length > 0 && (
                  <MessageAttachments attachments={m.attachments} />
                )}
                {m.content}
                <MessageStatus message={m} />
              </div>
            </li>
          ) : (
            <li
              key={m.key}
              data-role={m.role}
              data-status={m.status}
              className="relative flex w-full flex-col self-start md:pl-[42px]"
            >
              <span
                aria-hidden
                className="absolute top-0 left-0 hidden size-[30px] items-center justify-center rounded-full bg-brand-soft md:flex"
              >
                <LogoMark className="size-5" />
              </span>
              {/* The message itself; what the tutor did goes below it, outside the bubble. */}
              <div
                data-slot="message"
                className="self-start rounded-[6px_18px_18px_18px] border bg-card px-3.5 py-3 text-[15.5px] leading-[1.75] text-card-foreground md:px-[18px] md:py-3.5 md:text-base"
              >
                {m.attachments && m.attachments.length > 0 && (
                  <MessageAttachments attachments={m.attachments} />
                )}
                {!m.content ? (
                  m.status === "streaming" && <TypingDots label={t("typing")} />
                ) : (
                  <Markdown words>
                    {(m.id && translations.byId[m.id]?.showing && translations.byId[m.id].text) ||
                      m.content}
                  </Markdown>
                )}
                <MessageStatus message={m} />
              </div>
              {m.content && m.status !== "streaming" && (
                <ReplyTools
                  messageKey={m.key}
                  messageId={m.id}
                  content={m.content}
                  translation={m.id ? translations.byId[m.id] : undefined}
                  onTranslate={
                    conversationId ? (id, to) => void translations.toggle(id, to) : undefined
                  }
                />
              )}
              {cards && m.turnId && (
                <TutorCards cards={cards.byTurn[m.turnId] ?? []} onDecide={cards.decide} />
              )}
              {activity && m.turnId && m.status !== "streaming" && (
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
          ),
        )}
      </ol>
      <WordPopup container={listRef} />
    </div>
  );
}

/** Stopped or failed: said under the message, inside the bubble. */
function MessageStatus({ message: m }: { message: ChatMessage }) {
  const t = useTranslations("chat");
  const errorMessage = useErrorMessage();
  if (m.status === "stopped") {
    return <p className="mt-1 text-xs text-muted-foreground">{t("stopped")}</p>;
  }
  if (m.status === "error" && m.error) {
    return (
      <p role="alert" className="mt-1 text-xs text-destructive">
        {errorMessage(m.error)}
      </p>
    );
  }
  return null;
}

/** Three pulsing dots while the reply hasn't started. */
function TypingDots({ label }: { label: string }) {
  return (
    <span role="status" aria-label={label} className="inline-flex h-[1.75em] items-center gap-1">
      {[0, 150, 300].map((delay) => (
        <span
          key={delay}
          className="size-1.5 animate-pulse rounded-full bg-muted-foreground/60"
          style={{ animationDelay: `${delay}ms` }}
        />
      ))}
    </span>
  );
}
