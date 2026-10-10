"use client";

import { Mic } from "lucide-react";
import { useTranslations } from "next-intl";

import { AiBadge } from "@/components/ai-badge";
import { Button } from "@/components/ui/button";
import { useShadowingMode } from "@/lib/shadowing";
import { cn } from "@/lib/utils";

/** The AI mark of shadowing (ADR 0014): which kind depends on how it's scored. */
export function ShadowingBadge({ className }: { className?: string }) {
  const mode = useShadowingMode();
  if (!mode) return null;
  return (
    <AiBadge feature={mode === "assessment" ? "shadowing" : "shadowing_rough"} className={className} />
  );
}

/**
 * Opens and closes a `ShadowingPanel`. Nothing while shadowing can't be scored. `compact`
 * is the bare microphone at the end of a paragraph or an example sentence, whose AI mark
 * stands once nearby rather than on every one.
 */
export function ShadowingButton({
  open,
  onToggle,
  label,
  compact = false,
  className,
}: {
  open: boolean;
  /** Gets the button, to find the text it sits by. */
  onToggle: (button: HTMLElement) => void;
  /** What is read, for screen readers ("Shadow this paragraph"). */
  label?: string;
  compact?: boolean;
  className?: string;
}) {
  const t = useTranslations("speech.shadowing");
  const mode = useShadowingMode();
  if (!mode) return null;
  if (compact)
    return (
      <button
        type="button"
        aria-label={label ?? t("open")}
        title={label ?? t("open")}
        aria-expanded={open}
        onClick={(e) => onToggle(e.currentTarget)}
        data-testid="shadowing-open"
        className={cn(
          "inline-flex size-6 items-center justify-center rounded-sm align-[-5px] text-muted-foreground/70 hover:bg-muted hover:text-foreground",
          open && "bg-muted text-foreground",
          className,
        )}
      >
        <Mic aria-hidden className="size-3.5" />
      </button>
    );
  return (
    <>
      <Button
        size="xs"
        variant="ghost"
        aria-expanded={open}
        onClick={(e) => onToggle(e.currentTarget)}
        data-testid="shadowing-open"
        className={className}
      >
        <Mic />
        {t("open")}
      </Button>
      <ShadowingBadge />
    </>
  );
}
