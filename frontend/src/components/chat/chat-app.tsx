"use client";

import { useLocale, useTranslations } from "next-intl";
import Link from "next/link";
import { type DragEvent, useCallback, useEffect, useRef, useState } from "react";

import { buttonVariants } from "@/components/ui/button";
import { type ApiErrorLike, useErrorMessage } from "@/i18n/errors";
import { api, ApiError } from "@/lib/api";
import { useShowActivity } from "@/lib/preferences";
import type { Conversation } from "@/lib/types";

import { SETTINGS_ERRORS } from "./attachment-tray";
import { Composer } from "./composer";
import { ConversationList } from "./conversation-list";
import { MessageList } from "./message-list";
import { PlacementBanner } from "./placement-banner";
import { PracticeBar } from "./practice-bar";
import { useActivity } from "./use-activity";
import { useCards } from "./use-cards";
import { useAttachments } from "./use-attachments";
import { useChatSession } from "./use-chat-session";

// The active conversation lives in `?c=<id>`, updated with the History API so that
// creating a conversation mid-send doesn't remount the page and cut the stream.
function setUrl(id: string | null, mode: "push" | "replace" = "push") {
  const url = id ? `/chat?c=${id}` : "/chat";
  if (mode === "push") window.history.pushState(null, "", url);
  else window.history.replaceState(null, "", url);
}

export function ChatApp({
  initialId,
  practiceKc = null,
  planning = false,
}: {
  initialId: string | null;
  /** `?practice=<kc>`: start, or return to, a practice conversation on that grammar point. */
  practiceKc?: string | null;
  /** `?plan=1`: start, or return to, an empty study-planning conversation (ADR 0015 §6). */
  planning?: boolean;
}) {
  const t = useTranslations("chat");
  const locale = useLocale();
  const errorMessage = useErrorMessage();
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeId, setActiveId] = useState<string | null>(initialId);
  // The conversation made from `?practice=` or `?plan=`, in case the list loads without it.
  const [practice, setPractice] = useState<Conversation | null>(null);
  const [practiceError, setPracticeError] = useState<ApiErrorLike | null>(null);

  const refresh = useCallback(() => {
    api<Conversation[]>("/conversations").then(setConversations, () => {});
  }, []);
  useEffect(refresh, [refresh]);

  // Once per point and page load (StrictMode runs effects twice). Coming back to the same
  // point returns its unstarted practice conversation instead of a new one (Q19c); an
  // empty planning conversation is returned likewise.
  const practiceStarted = useRef<string | null>(null);
  const purpose = planning ? "planning" : practiceKc ? `practice:${practiceKc}` : null;
  useEffect(() => {
    if (!purpose || practiceStarted.current === purpose) return;
    practiceStarted.current = purpose;
    api<Conversation>("/conversations", {
      method: "POST",
      json: planning ? { purpose: "planning", locale } : { focus_kc_id: practiceKc, locale },
    }).then(
      (c) => {
        setPractice(c);
        setConversations((all) => [c, ...all.filter((o) => o.id !== c.id)]);
        setActiveId(c.id);
        setUrl(c.id, "replace");
      },
      (e: unknown) =>
        setPracticeError(e instanceof ApiError ? e : { code: "network_error", message: "" }),
    );
  }, [purpose, planning, practiceKc, locale]);

  useEffect(() => {
    const onPop = () => setActiveId(new URLSearchParams(window.location.search).get("c"));
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  const [showActivity] = useShowActivity();
  const activity = useActivity(activeId, showActivity);
  const cards = useCards(activeId);
  const session = useChatSession(activeId, {
    onConversationCreated: (c) => {
      setActiveId(c.id);
      setUrl(c.id, "replace");
      setConversations((all) => [c, ...all]);
    },
    onTurnFinished: () => {
      refresh();
      cards.reload(); // current statuses, and live numbers for link cards
    },
    onActivity: activity.addLive,
    onCard: cards.add,
    onReplyDone: activity.turnFinished,
  });
  const tray = useAttachments(activeId, session.ensureConversation);

  const active =
    conversations.find((c) => c.id === activeId) ??
    (practice?.id === activeId ? practice : undefined);
  // A practice or planning conversation with nothing in it yet: the tutor speaks first
  // (Q19a, ADR 0015 §6). Tried once per conversation and page load, so a refusal (e.g. no
  // model) doesn't loop.
  const opened = useRef(new Set<string>());
  const { readyFor, messages, streaming, open } = session;
  useEffect(() => {
    const opens = active?.focus_kc || active?.purpose === "planning";
    if (!active || !opens || readyFor !== active.id || opened.current.has(active.id)) return;
    if (messages.length > 0 || streaming) return;
    opened.current.add(active.id);
    void open();
  }, [active, readyFor, messages.length, streaming, open]);
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

  const error = session.error ?? practiceError;
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
        {active?.focus_kc ? <PracticeBar kc={active.focus_kc} /> : <PlacementBanner />}
        <MessageList
          messages={session.messages}
          activity={showActivity ? activity : undefined}
          cards={cards}
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
        />
      </section>
    </>
  );
}
