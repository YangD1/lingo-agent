"use client";

import { useTranslations } from "next-intl";
import { useEffect, useRef } from "react";

import { useErrorMessage } from "@/i18n/errors";
import { cn } from "@/lib/utils";

import { Markdown } from "./markdown";
import { MessageAttachments } from "./message-attachments";
import { TurnActivity } from "./turn-activity";
import type { ActivityState } from "./use-activity";
import type { ChatMessage } from "./use-chat-session";

export function MessageList({
  messages,
  activity,
}: {
  messages: ChatMessage[];
  /** What the tutor did per turn; absent when the learner hid it. */
  activity?: ActivityState;
}) {
  const t = useTranslations("chat");
  const errorMessage = useErrorMessage();
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: "end" });
  }, [messages]);

  if (messages.length === 0) {
    return (
      <div className="flex flex-1 items-center justify-center p-8 text-center text-muted-foreground">
        {t("empty")}
      </div>
    );
  }

  return (
    <div className="min-h-0 flex-1 overflow-y-auto">
      <ol className="mx-auto flex max-w-3xl flex-col gap-4 p-4" aria-label={t("messages")}>
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
                <Markdown>{m.content}</Markdown>
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
            {activity && m.role === "assistant" && m.turnId && m.status !== "streaming" && (
              <TurnActivity
                activities={activity.byTurn[m.turnId] ?? []}
                memories={activity.memories}
                kcs={activity.kcs}
                waiting={activity.waiting.has(m.turnId)}
              />
            )}
          </li>
        ))}
      </ol>
      <div ref={bottomRef} />
    </div>
  );
}
