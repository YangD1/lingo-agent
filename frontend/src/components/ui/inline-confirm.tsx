"use client";

import { useTranslations } from "next-intl";
import { type ReactNode, useState } from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/**
 * Confirmation for deleting a single item (component-spec §15): the delete button turns into
 * the question with "Delete" / "Cancel" in its place. `children` renders that button and gets
 * the function that asks.
 */
export function InlineConfirm({
  question,
  confirmLabel,
  onConfirm,
  children,
  compact = false,
  className,
}: {
  question: string;
  /** Defaults to "Delete". */
  confirmLabel?: string;
  onConfirm: () => void;
  children: (ask: () => void) => ReactNode;
  /** One line: the question is cut off instead of wrapping (narrow rows). */
  compact?: boolean;
  className?: string;
}) {
  const t = useTranslations("confirm");
  const [asking, setAsking] = useState(false);
  if (!asking) return children(() => setAsking(true));
  return (
    <span
      role="group"
      aria-label={question}
      className={cn(
        "inline-flex items-center justify-end gap-1.5",
        compact ? "flex-nowrap" : "flex-wrap",
        className,
      )}
      onKeyDown={(e) => {
        if (e.key === "Escape") setAsking(false);
      }}
    >
      <span
        title={compact ? question : undefined}
        className={cn("text-xs text-muted-foreground", compact ? "min-w-0 flex-1 truncate" : "max-w-64")}
      >
        {question}
      </span>
      <Button
        size="sm"
        variant="destructive"
        autoFocus
        onClick={() => {
          setAsking(false);
          onConfirm();
        }}
      >
        {confirmLabel ?? t("delete")}
      </Button>
      <Button size="sm" variant="ghost" onClick={() => setAsking(false)}>
        {t("cancel")}
      </Button>
    </span>
  );
}
