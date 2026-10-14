"use client";

import { ExternalLinkIcon, PlugIcon, XIcon } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { useEffect, useRef, useState, useSyncExternalStore } from "react";

import { TutorPanel } from "@/components/chat/tutor-panel";
import { buttonVariants } from "@/components/ui/button";
import { Callout } from "@/components/ui/callout";
import { api } from "@/lib/api";
import { matchAction, type PetAction, petAction, QUICK_ACTIONS } from "@/lib/pet-actions";
import {
  type ChatSize,
  DEFAULT_CHAT_SIZE,
  fitChatSize,
  keepChatSize,
  readChatSize,
  type Viewport,
} from "@/lib/pet-chat-size";
import type { Conversation } from "@/lib/types";
import { cn } from "@/lib/utils";

// The conversation the window is on, kept while the app is open: reopening goes on with it.
let kept: Conversation | null = null;

/** A plain click on a link within the app, which goes somewhere else in it. */
function leadsAway(e: React.MouseEvent): boolean {
  if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return false;
  const link = e.target instanceof Element ? e.target.closest("a[href]") : null;
  if (!(link instanceof HTMLAnchorElement) || (link.target && link.target !== "_self")) return false;
  return new URL(link.href, window.location.href).origin === window.location.origin;
}

/** The window's size in CSS pixels, followed as it changes. */
function useViewport(): Viewport {
  const at = useSyncExternalStore(
    (listener) => {
      window.addEventListener("resize", listener);
      return () => window.removeEventListener("resize", listener);
    },
    () => `${window.innerWidth}x${window.innerHeight}`,
    () => "1280x800",
  );
  const [width, height] = at.split("x").map(Number);
  return { width, height };
}

/** Where the window is resized from: its top edge, its far side, or the corner between. */
type Grip = "top" | "side" | "corner";

/** One press of an arrow key on the corner grip. */
const KEY_STEP = 32;

/**
 * Resizing the window by its free edges (task 77, Q77a/b): the side by the pet and the
 * bottom stay put. Null size: the default, from the classes.
 */
function useResize(side: "left" | "right") {
  const viewport = useViewport();
  const [chosen, setChosen] = useState<ChatSize | null>(readChatSize);
  const [resizing, setResizing] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const start = useRef<{ x: number; y: number; size: ChatSize; grip: Grip } | null>(null);
  const latest = useRef<ChatSize | null>(null);

  const current = (): ChatSize => {
    const rect = box.current?.getBoundingClientRect();
    return rect ? { width: rect.width, height: rect.height } : fitChatSize(chosen ?? DEFAULT_CHAT_SIZE, viewport);
  };
  const choose = (size: ChatSize | null) => {
    const fitted = size && fitChatSize(size, viewport);
    latest.current = fitted;
    setChosen(fitted);
    return fitted;
  };
  // Toward the far side is wider: left on the right edge, right on the left.
  const wider = (dx: number) => (side === "right" ? -dx : dx);

  const grip = (which: Grip) => ({
    onPointerDown: (e: React.PointerEvent<HTMLElement>) => {
      if (e.button !== 0) return;
      e.preventDefault();
      e.currentTarget.setPointerCapture(e.pointerId);
      start.current = { x: e.clientX, y: e.clientY, size: current(), grip: which };
      setResizing(true);
    },
    onPointerMove: (e: React.PointerEvent<HTMLElement>) => {
      const from = start.current;
      if (!from) return;
      choose({
        width: from.grip === "top" ? from.size.width : from.size.width + wider(e.clientX - from.x),
        height: from.grip === "side" ? from.size.height : from.size.height - (e.clientY - from.y),
      });
    },
    onPointerUp: () => {
      if (!start.current) return;
      start.current = null;
      setResizing(false);
      if (latest.current) keepChatSize(latest.current);
    },
    onPointerCancel: () => {
      start.current = null;
      setResizing(false);
    },
    onDoubleClick: () => {
      choose(null);
      keepChatSize(null);
    },
  });

  const onKeyDown = (e: React.KeyboardEvent) => {
    const step = { ArrowLeft: [-KEY_STEP, 0], ArrowRight: [KEY_STEP, 0], ArrowUp: [0, KEY_STEP], ArrowDown: [0, -KEY_STEP] }[
      e.key
    ];
    if (!step) return;
    e.preventDefault();
    const size = current();
    const fitted = choose({ width: size.width + wider(step[0]), height: size.height + step[1] });
    if (fitted) keepChatSize(fitted);
  };

  const style = chosen ? fitChatSize(chosen, viewport) : undefined;
  return { box, style, resizing, grip, onKeyDown };
}

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
 *
 * A row of shortcuts sits on top, and a short command ("背单词") goes to the pet instead of
 * the tutor (ADR 0039 §2): `onCommand` gets it, and nothing is sent. Without a chat model
 * the window says so first, so the shortcuts and the way to set one up are what it offers.
 */
export function PetChat({
  name,
  side,
  onClose,
  onCommand,
  modelReady = true,
  draft,
  wide = false,
}: {
  name: string;
  /** The pet's edge: the window opens on that side. */
  side: "left" | "right";
  onClose: () => void;
  /** A message that asked for one of the pet's actions, and what was said. */
  onCommand?: (action: PetAction, said: string) => void;
  /** Whether a chat model is set up; false shows the way to set one up. */
  modelReady?: boolean;
  /** What the input box starts with: a command the learner chose to ask the tutor after
   * all, so it is sent as it is, not taken as a command again. */
  draft?: string;
  /** A wide screen: the window sits by the pet and can be resized; on phones it fills most
   * of the screen. */
  wide?: boolean;
}) {
  const t = useTranslations("tutorPet");
  const tActions = useTranslations("tutorPet.actions");
  const tBubble = useTranslations("tutorPet.bubble");
  // undefined: still finding the conversation to go on with.
  const [conversation, setConversation] = useState<Conversation | null | undefined>(kept ?? undefined);
  const { box, style, resizing, grip, onKeyDown } = useResize(side);
  const shortcuts = useRef<HTMLDivElement>(null);

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

  // The wheel scrolls the shortcuts sideways, instead of the page behind the window.
  useEffect(() => {
    const row = shortcuts.current;
    if (!row) return;
    const onWheel = (e: WheelEvent) => {
      if (Math.abs(e.deltaX) >= Math.abs(e.deltaY) || row.scrollWidth <= row.clientWidth) return;
      e.preventDefault();
      row.scrollLeft += e.deltaY;
    };
    row.addEventListener("wheel", onWheel, { passive: false });
    return () => row.removeEventListener("wheel", onWheel);
  }, []);

  const chatHref = conversation ? `/chat?c=${conversation.id}` : "/chat";
  const setup = petAction("setup_models");
  return (
    <div
      ref={box}
      role="dialog"
      aria-label={t("chatTitle", { name })}
      data-testid="pet-chat"
      // A card's link leads away from the chat (ADR 0039 §2): the window makes way. Links to
      // flashcards never get here (the overlay's host takes them first); the pet closes the
      // window when the overlay opens.
      onClickCapture={(e) => {
        if (leadsAway(e)) onClose();
      }}
      style={wide ? style : undefined}
      className={cn(
        // Apart from the page (task 78): its own ground under the bubbles, a brand edge and a
        // deeper shadow; the corner by the pet is tighter, a speech bubble pointing at it.
        "fixed z-50 flex flex-col overflow-hidden rounded-2xl border border-(--pet-edge) bg-(--pet-surface) shadow-(--shadow-pet)",
        // Phones: most of the screen, above the tab bar; wider screens: a window by the pet,
        // 28rem × 44rem unless resized (DEFAULT_CHAT_SIZE).
        "inset-x-2 top-16 bottom-[calc(4rem+env(safe-area-inset-bottom)+8px)]",
        "md:inset-x-auto md:top-auto md:bottom-4 md:h-[min(44rem,calc(100dvh-2rem))] md:w-[min(28rem,calc(100vw-8rem))]",
        side === "right" ? "md:right-28 md:rounded-br-sm" : "md:left-28 md:rounded-bl-sm",
        // Not over the page: no room kept for the pet below the last message, and the chat
        // page's wide side padding is too much for a window.
        "[--pet-safe:0px] md:[&_[data-chat-gutter]]:px-4",
        resizing && "select-none",
      )}
    >
      {wide && <ResizeGrips side={side} label={t("resize")} grip={grip} onKeyDown={onKeyDown} />}
      <header className="flex h-11 shrink-0 items-center gap-1 bg-brand-soft pr-1 pl-3.5">
        <h2 className="min-w-0 flex-1 truncate text-sm font-semibold">
          {conversation?.title || t("chatTitle", { name })}
        </h2>
        <Link
          href={chatHref}
          className={cn(buttonVariants({ size: "sm", variant: "ghost" }), "hover:bg-background/70")}
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
          className="flex size-8 items-center justify-center rounded-md text-muted-foreground outline-none hover:bg-background/70 hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50 [&_svg]:size-4"
        >
          <XIcon aria-hidden />
        </button>
      </header>
      <nav
        aria-label={tBubble("quick")}
        className="flex shrink-0 flex-col gap-2 border-b border-(--pet-edge) bg-brand-soft px-3 pt-0.5 pb-2.5"
        data-testid="pet-chat-shortcuts"
      >
        {!modelReady && (
          <Callout
            tone="warning"
            icon={<PlugIcon aria-hidden />}
            data-testid="pet-chat-no-model"
            action={
              <Link href={setup.href} className={buttonVariants({ size: "sm" })}>
                {tActions("setup_models.label")}
              </Link>
            }
          >
            {tBubble("noModel")}
          </Callout>
        )}
        <div ref={shortcuts} className="scroll-row -mx-3 flex gap-1.5 px-3">
          {QUICK_ACTIONS.map((id) => {
            const quick = petAction(id);
            const Icon = quick.icon;
            return (
              <Link
                key={id}
                href={quick.href}
                className="flex h-7 shrink-0 items-center gap-1.5 rounded-full bg-background/75 px-2.5 text-xs font-medium whitespace-nowrap text-foreground/80 shadow-xs transition-colors hover:bg-background hover:text-foreground [&_svg]:size-3.5 [&_svg]:text-brand-soft-foreground"
              >
                <Icon aria-hidden />
                {tActions(`${id}.label`)}
              </Link>
            );
          })}
        </div>
      </nav>
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
          initialText={draft}
          beforeSend={(text, attachments) => {
            if (!onCommand || attachments.length > 0 || text === draft) return false;
            const found = matchAction(text);
            if (!found) return false;
            onCommand(found, text);
            return true;
          }}
        />
      )}
    </div>
  );
}

/**
 * The free edges of the window (Q77a): the top, the side away from the pet, and the corner
 * between them, which also takes the arrow keys. Double-clicking any goes back to the
 * default size.
 */
function ResizeGrips({
  side,
  label,
  grip,
  onKeyDown,
}: {
  side: "left" | "right";
  label: string;
  grip: ReturnType<typeof useResize>["grip"];
  onKeyDown: (e: React.KeyboardEvent) => void;
}) {
  const far = side === "right" ? "left-0" : "right-0";
  return (
    <>
      <div aria-hidden className="absolute inset-x-4 top-0 z-20 h-1.5 cursor-ns-resize" {...grip("top")} />
      <div aria-hidden className={cn("absolute inset-y-4 z-20 w-1.5 cursor-ew-resize", far)} {...grip("side")} />
      <button
        type="button"
        aria-label={label}
        title={label}
        data-testid="pet-chat-resize"
        onKeyDown={onKeyDown}
        className={cn(
          "absolute top-0 z-20 size-5 touch-none outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
          side === "right" ? "left-0 cursor-nwse-resize rounded-tl-2xl" : "right-0 cursor-nesw-resize rounded-tr-2xl",
        )}
        {...grip("corner")}
      />
    </>
  );
}
