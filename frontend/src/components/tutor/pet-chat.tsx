"use client";

import { ExternalLinkIcon, XIcon } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import { TutorPanel } from "@/components/chat/tutor-panel";
import { buttonVariants } from "@/components/ui/button";
import { api } from "@/lib/api";
import type { Conversation } from "@/lib/types";
import { cn } from "@/lib/utils";

// The conversation the window is on, kept while the app is open: reopening goes on with it.
let kept: Conversation | null = null;

/** Forgets the kept conversation (tests). */
export function resetPetChat() {
  kept = null;
}

/**
 * The conversation to go on with (Q66m): the most recent one in the chat page's list (a
 * message moves a conversation to the top); null for a new chat.
 */
export async function latestConversation(): Promise<Conversation | null> {
  const list = await api<Conversation[]>("/conversations");
  return list[0] ?? null;
}

/**
 * The desk pet's chat window (ADR 0032 §4a): the tutor in a small window over the page,
 * going on with the latest conversation, the same as on the chat page. It doesn't see the
 * page it is over (Q66n). Escape or the close button closes it.
 */
export function PetChat({
  name,
  side,
  onClose,
}: {
  name: string;
  /** The pet's edge: the window opens on that side. */
  side: "left" | "right";
  onClose: () => void;
}) {
  const t = useTranslations("tutorPet");
  // undefined: still finding the conversation to go on with.
  const [conversation, setConversation] = useState<Conversation | null | undefined>(kept ?? undefined);

  useEffect(() => {
    let live = true;
    latestConversation().then(
      (latest) => {
        if (!live) return;
        kept = latest;
        setConversation(latest);
      },
      // The list can't be had: a new chat, created with the first message.
      () => live && setConversation((c) => c ?? null),
    );
    return () => {
      live = false;
    };
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !e.defaultPrevented) onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const chatHref = conversation ? `/chat?c=${conversation.id}` : "/chat";
  return (
    <div
      role="dialog"
      aria-label={t("chatTitle", { name })}
      data-testid="pet-chat"
      className={cn(
        "fixed z-50 flex flex-col overflow-hidden rounded-xl border bg-background shadow-(--shadow-pop)",
        // Phones: most of the screen, above the tab bar; wider screens: a window by the pet.
        "inset-x-2 top-16 bottom-[calc(4rem+env(safe-area-inset-bottom)+8px)]",
        "md:inset-x-auto md:top-auto md:bottom-4 md:h-[min(36rem,calc(100dvh-2rem))] md:w-[24rem]",
        side === "right" ? "md:right-28" : "md:left-28",
      )}
    >
      <header className="flex h-11 shrink-0 items-center gap-1 border-b pr-1 pl-3">
        <h2 className="min-w-0 flex-1 truncate text-sm font-semibold">
          {conversation?.title || t("chatTitle", { name })}
        </h2>
        <Link
          href={chatHref}
          onClick={onClose}
          className={buttonVariants({ size: "sm", variant: "ghost" })}
          data-testid="pet-chat-open-in-chat"
        >
          <ExternalLinkIcon aria-hidden />
          {t("openInChat")}
        </Link>
        <button
          type="button"
          aria-label={t("close")}
          title={t("close")}
          onClick={onClose}
          className="flex size-8 items-center justify-center rounded-md text-muted-foreground outline-none hover:bg-accent hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50 [&_svg]:size-4"
        >
          <XIcon aria-hidden />
        </button>
      </header>
      {conversation !== undefined && (
        <TutorPanel
          className="min-h-0 flex-1"
          conversationId={conversation?.id ?? null}
          onConversationCreated={(c) => {
            kept = c;
            setConversation(c);
          }}
          onTurnFinished={() => {
            // The backend may have retitled it.
            latestConversation().then((latest) => {
              if (latest && latest.id === kept?.id) setConversation((kept = latest));
            }, () => {});
          }}
          sendFeature={conversation?.article_id ? "reading_coach" : undefined}
          // Open to typing.
          autoFocus
        />
      )}
    </div>
  );
}
