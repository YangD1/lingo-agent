"use client";

import { LayoutGridIcon, Menu } from "lucide-react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { useCallback, useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Sheet } from "@/components/ui/sheet";
import type { ApiErrorLike } from "@/i18n/errors";
import { api, ApiError } from "@/lib/api";
import type { Conversation } from "@/lib/types";

import { ConversationList } from "./conversation-list";
import { PlacementBanner } from "./placement-banner";
import { PracticeBar } from "./practice-bar";
import { ReadingBar } from "./reading-bar";
import { TutorPanel } from "./tutor-panel";

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
  const locale = useLocale();
  const t = useTranslations("chat");
  const tNav = useTranslations("nav");
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  // Coming back (browser Back) to a page opened with `?practice=` or `?plan=`, Next may
  // render the props it cached for that URL, though `setUrl` has since replaced it with
  // the conversation made from it: the address bar is the truth.
  const [urlId] = useState(() =>
    typeof window === "undefined" ? null : new URLSearchParams(window.location.search).get("c"),
  );
  const [activeId, setActiveId] = useState<string | null>(urlId ?? initialId);
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
    if (!purpose || urlId || practiceStarted.current === purpose) return;
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
  }, [purpose, urlId, planning, practiceKc, locale]);

  useEffect(() => {
    const onPop = () => setActiveId(new URLSearchParams(window.location.search).get("c"));
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  const active =
    conversations.find((c) => c.id === activeId) ??
    (practice?.id === activeId ? practice : undefined);

  const select = (id: string | null) => {
    setActiveId(id);
    setUrl(id);
  };

  async function remove(id: string) {
    await api(`/conversations/${id}`, { method: "DELETE" }).catch(() => {});
    setConversations((all) => all.filter((c) => c.id !== id));
    if (id === activeId) select(null);
  }

  const list = {
    conversations,
    activeId,
    onDelete: remove,
  };

  return (
    <>
      <ConversationList
        {...list}
        className="hidden md:flex"
        onSelect={select}
        onNew={() => select(null)}
      />
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 shrink-0 items-center gap-1.5 border-b px-2 md:h-12 md:px-5">
          <Button
            variant="ghost"
            size="icon"
            className="md:hidden"
            aria-label={t("openConversations")}
            aria-haspopup="dialog"
            onClick={() => setDrawerOpen(true)}
          >
            <Menu className="size-5" />
          </Button>
          <h1 className="truncate text-base font-semibold md:text-[15px]">
            {active ? active.title || t("untitled") : t("newChat")}
          </h1>
        </header>
        <TutorPanel
          className="min-h-0 flex-1"
          conversationId={activeId}
          onConversationCreated={(c) => {
            setActiveId(c.id);
            setUrl(c.id, "replace");
            setConversations((all) => [c, ...all.filter((o) => o.id !== c.id)]);
          }}
          onTurnFinished={refresh}
          // A practice or planning conversation with nothing in it yet (Q19a, ADR 0015 §6).
          autoOpen={Boolean(active?.focus_kc || active?.purpose === "planning")}
          header={
            active?.focus_kc ? (
              <PracticeBar kc={active.focus_kc} />
            ) : active?.article_id ? (
              <ReadingBar articleId={active.article_id} />
            ) : (
              <PlacementBanner />
            )
          }
          sendFeature={active?.article_id ? "reading_coach" : undefined}
          error={practiceError}
        />
      </div>
      {/* Phones: the list is a drawer, and the way back to the other pages (no tab bar here). */}
      <Sheet
        side="left"
        open={drawerOpen}
        onOpenChange={setDrawerOpen}
        title={t("conversations")}
        hideTitle
        className="bg-[color-mix(in_oklab,var(--sidebar)_60%,var(--background))]"
      >
        <ConversationList
          {...list}
          className="min-h-0 w-full flex-1 border-r-0 bg-transparent"
          onSelect={(id) => {
            setDrawerOpen(false);
            select(id);
          }}
          onNew={() => {
            setDrawerOpen(false);
            select(null);
          }}
        />
        <Link
          href="/dashboard"
          className="flex h-12 shrink-0 items-center gap-2.5 border-t px-5 text-sm text-muted-foreground hover:text-foreground"
        >
          <LayoutGridIcon aria-hidden className="size-[18px]" />
          {tNav("dashboard")}
        </Link>
      </Sheet>
    </>
  );
}
