"use client";

import { MessageSquareQuote } from "lucide-react";
import { useTranslations } from "next-intl";
import { type ReactNode, useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { DEFAULT_TUTOR, useTutor } from "@/lib/tutor";
import { cn } from "@/lib/utils";

type Picked = { text: string; top: number; left: number };

/** The selection inside `box`, and where above it to show the button (box coordinates). */
function picked(box: HTMLElement): Picked | null {
  const selection = window.getSelection();
  if (!selection || selection.isCollapsed || selection.rangeCount === 0) return null;
  const range = selection.getRangeAt(0);
  if (!box.contains(range.commonAncestorContainer)) return null;
  const text = selection.toString().trim();
  if (!text) return null;
  const rect = range.getBoundingClientRect();
  const outer = box.getBoundingClientRect();
  return {
    text,
    top: Math.max(rect.top - outer.top - 40, 0),
    left: Math.min(Math.max(rect.left - outer.left + rect.width / 2, 60), outer.width - 60),
  };
}

/**
 * Select text in the document → "Ask {name}" above it (ADR 0043 §4): the selection goes into
 * the input box as a quote. The button keeps the selection (no focus change on press).
 */
export function SelectionAsk({
  onAsk,
  children,
  className,
}: {
  onAsk: (text: string) => void;
  children: ReactNode;
  className?: string;
}) {
  const t = useTranslations("chat.workspace");
  const name = useTutor()?.display_name ?? DEFAULT_TUTOR.display_name;
  const box = useRef<HTMLDivElement>(null);
  const [pick, setPick] = useState<Picked | null>(null);

  const check = () => setPick(box.current ? picked(box.current) : null);

  // Clicking elsewhere or clearing the selection hides it.
  useEffect(() => {
    const onChange = () => {
      if (window.getSelection()?.isCollapsed) setPick(null);
    };
    document.addEventListener("selectionchange", onChange);
    return () => document.removeEventListener("selectionchange", onChange);
  }, []);

  return (
    <div
      ref={box}
      className={cn("relative", className)}
      onMouseUp={check}
      onKeyUp={check}
      onTouchEnd={() => setTimeout(check, 0)}
    >
      {children}
      {pick && (
        <Button
          type="button"
          size="sm"
          data-testid="ask-about-selection"
          className="absolute z-10 -translate-x-1/2 shadow-(--shadow-pop)"
          style={{ top: pick.top, left: pick.left }}
          onMouseDown={(e) => e.preventDefault()}
          onClick={() => {
            onAsk(pick.text);
            window.getSelection()?.removeAllRanges();
            setPick(null);
          }}
        >
          <MessageSquareQuote />
          {t("ask", { name })}
        </Button>
      )}
    </div>
  );
}
