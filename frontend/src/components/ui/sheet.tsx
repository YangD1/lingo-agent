"use client";

import { Dialog } from "@base-ui/react/dialog";
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

/**
 * A modal panel sliding in from the bottom (phone "More" panel) or the left (chat drawer).
 * Built on Base UI's Dialog, so focus is trapped and Escape / backdrop close it.
 */
export function Sheet({
  open,
  onOpenChange,
  side = "bottom",
  title,
  hideTitle = false,
  children,
  className,
  ...props
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  side?: "bottom" | "left";
  /** Accessible name; shown as a small heading. */
  title: string;
  /** Keep the title for screen readers only, when the content makes it obvious. */
  hideTitle?: boolean;
  children: ReactNode;
  className?: string;
  "data-testid"?: string;
}) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Backdrop className="fixed inset-0 z-50 bg-foreground/32 transition-opacity duration-150 data-ending-style:opacity-0 data-starting-style:opacity-0" />
        <Dialog.Popup
          className={cn(
            "fixed z-50 flex flex-col bg-popover text-popover-foreground shadow-(--shadow-pop) outline-none transition-transform duration-200",
            side === "bottom"
              ? "inset-x-0 bottom-0 max-h-[85dvh] rounded-t-2xl border-t px-4 pt-2 pb-[max(1rem,env(safe-area-inset-bottom))] data-ending-style:translate-y-full data-starting-style:translate-y-full"
              : "inset-y-0 left-0 w-[300px] max-w-[85vw] border-r data-ending-style:-translate-x-full data-starting-style:-translate-x-full",
            className,
          )}
          {...props}
        >
          {side === "bottom" && <span aria-hidden className="mx-auto mb-2 h-1 w-9 rounded-full bg-border" />}
          <Dialog.Title
            className={cn(
              "text-[13px] font-semibold text-muted-foreground",
              side === "left" && "px-4 pt-4",
              hideTitle && "sr-only",
            )}
          >
            {title}
          </Dialog.Title>
          {children}
        </Dialog.Popup>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
