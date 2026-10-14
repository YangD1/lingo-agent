"use client";

import { XIcon } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/** What the pet says in its bubble, already in the learner's language. */
export type BubbleContent = {
  /** Which one: the pet's records of what it said, and tests. */
  key: string;
  text: string;
  /** The way in: a plain link, so flashcards open in place (ADR 0038). */
  action?: { href: string; label: string };
  /** "No thanks" / "Later"; left out, only the close button. */
  dismiss?: string;
  /** A quieter way out under the buttons ("Ask the tutor instead"). */
  aside?: { label: string; onClick: () => void };
  /** Gone after this long untouched. */
  lingerMs: number;
};

export type BubbleEnd = "action" | "dismiss" | "timeout";

/**
 * The pet's speech bubble (ADR 0039 §3): above its head, toward the middle of the screen.
 * It goes after `lingerMs`, waiting while the pointer or focus is on it.
 */
export function PetBubble({
  content,
  side,
  onEnd,
}: {
  content: BubbleContent;
  /** The pet's edge: the bubble lines up with it and leans inward. */
  side: "left" | "right";
  onEnd: (how: BubbleEnd) => void;
}) {
  const t = useTranslations("tutorPet.bubble");
  const [held, setHeld] = useState({ hover: false, focus: false });
  const waiting = held.hover || held.focus;

  useEffect(() => {
    if (waiting) return;
    const timer = setTimeout(() => onEnd("timeout"), content.lingerMs);
    return () => clearTimeout(timer);
  }, [waiting, content, onEnd]);

  return (
    <div
      data-testid="pet-bubble"
      data-key={content.key}
      // Not a drag of the pet underneath, and no tap on it.
      onPointerDown={(e) => e.stopPropagation()}
      onClick={(e) => e.stopPropagation()}
      onPointerEnter={() => setHeld((h) => ({ ...h, hover: true }))}
      onPointerLeave={() => setHeld((h) => ({ ...h, hover: false }))}
      onFocus={() => setHeld((h) => ({ ...h, focus: true }))}
      onBlur={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget as Node | null)) {
          setHeld((h) => ({ ...h, focus: false }));
        }
      }}
      className={cn(
        "absolute bottom-[calc(100%+10px)] w-max max-w-[min(17rem,calc(100vw-2rem))] cursor-auto select-text",
        "rounded-2xl border bg-popover p-3 pr-8 text-sm text-popover-foreground shadow-(--shadow-pop)",
        "motion-safe:animate-in motion-safe:fade-in motion-safe:zoom-in-95 motion-safe:slide-in-from-bottom-1",
        side === "right" ? "right-0 origin-bottom-right" : "left-0 origin-bottom-left",
      )}
    >
      <p role="status" className="leading-snug">
        {content.text}
      </p>
      {(content.action || content.dismiss) && (
        <div className="mt-2.5 flex flex-wrap gap-2">
          {content.action && (
            <Link
              href={content.action.href}
              onClick={() => onEnd("action")}
              className={buttonVariants({ size: "sm" })}
              data-testid="pet-bubble-action"
            >
              {content.action.label}
            </Link>
          )}
          {content.dismiss && (
            <button
              type="button"
              onClick={() => onEnd("dismiss")}
              className={buttonVariants({ size: "sm", variant: "ghost" })}
            >
              {content.dismiss}
            </button>
          )}
        </div>
      )}
      {content.aside && (
        <button
          type="button"
          onClick={() => {
            content.aside?.onClick();
            onEnd("dismiss");
          }}
          className="mt-1.5 text-xs text-muted-foreground underline-offset-4 hover:text-foreground hover:underline"
        >
          {content.aside.label}
        </button>
      )}
      <button
        type="button"
        aria-label={t("close")}
        title={t("close")}
        onClick={() => onEnd("dismiss")}
        className="absolute top-1.5 right-1.5 flex size-6 items-center justify-center rounded-md text-muted-foreground outline-none hover:bg-accent hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50 [&_svg]:size-3.5"
      >
        <XIcon aria-hidden />
      </button>
      {/* The tail, toward the pet. */}
      <span
        aria-hidden
        className={cn(
          "absolute -bottom-[7px] size-3 rotate-45 border-r border-b bg-popover",
          side === "right" ? "right-9" : "left-9",
        )}
      />
    </div>
  );
}
