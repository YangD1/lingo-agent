"use client";

import { useTranslations } from "next-intl";
import Link from "next/link";
import { type DragEvent, useCallback, useEffect, useState } from "react";

import { buttonVariants } from "@/components/ui/button";
import { useErrorMessage } from "@/i18n/errors";
import { api } from "@/lib/api";
import { useShowActivity } from "@/lib/preferences";
import type { Conversation } from "@/lib/types";

import { SETTINGS_ERRORS } from "./attachment-tray";
import { Composer } from "./composer";
import { ConversationList } from "./conversation-list";
import { MessageList } from "./message-list";
import { useActivity } from "./use-activity";
import { useAttachments } from "./use-attachments";
import { useChatSession } from "./use-chat-session";

// The active conversation lives in `?c=<id>`, updated with the History API so that
// creating a conversation mid-send doesn't remount the page and cut the stream.
function setUrl(id: string | null, mode: "push" | "replace" = "push") {
  const url = id ? `/chat?c=${id}` : "/chat";
  if (mode === "push") window.history.pushState(null, "", url);
  else window.history.replaceState(null, "", url);
}

export function ChatApp({ initialId }: { initialId: string | null }) {
  const t = useTranslations("chat");
  const errorMessage = useErrorMessage();
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeId, setActiveId] = useState<string | null>(initialId);

  const refresh = useCallback(() => {
    api<Conversation[]>("/conversations").then(setConversations, () => {});
  }, []);
  useEffect(refresh, [refresh]);

  useEffect(() => {
    const onPop = () => setActiveId(new URLSearchParams(window.location.search).get("c"));
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  const [showActivity] = useShowActivity();
  const activity = useActivity(activeId, showActivity);
  const session = useChatSession(activeId, {
    onConversationCreated: (c) => {
      setActiveId(c.id);
      setUrl(c.id, "replace");
      setConversations((all) => [c, ...all]);
    },
    onTurnFinished: refresh,
    onActivity: activity.addLive,
    onReplyDone: activity.turnFinished,
  });
  const tray = useAttachments(activeId, session.ensureConversation);
  const [dragging, setDragging] = useState(false);

  const hasFiles = (event: DragEvent) => event.dataTransfer.types.includes("Files");
  function onDrop(event: DragEvent) {
    if (!hasFiles(event)) return;
    event.preventDefault();
    setDragging(false);
    if (!session.loading) tray.add(Array.from(event.dataTransfer.files));
  }

  const select = (id: string | null) => {
    setActiveId(id);
    setUrl(id);
  };

  async function remove(id: string) {
    await api(`/conversations/${id}`, { method: "DELETE" }).catch(() => {});
    setConversations((all) => all.filter((c) => c.id !== id));
    if (id === activeId) select(null);
  }

  const error = session.error;
  return (
    <>
      <ConversationList
        conversations={conversations}
        activeId={activeId}
        onSelect={select}
        onNew={() => select(null)}
        onDelete={remove}
      />
      <section
        className="relative flex min-w-0 flex-1 flex-col"
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
        <MessageList messages={session.messages} activity={showActivity ? activity : undefined} />
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
        />
      </section>
    </>
  );
}
