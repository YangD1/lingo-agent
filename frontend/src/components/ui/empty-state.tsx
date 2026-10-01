import type { ReactNode } from "react";

import { LingoCat } from "@/components/brand/lingo-cat";
import { cn } from "@/lib/utils";

/**
 * Empty and error states (component-spec §16): the cat (idle, or oops for errors — task 29),
 * one bold line saying what the situation is, one line saying what would improve it, and at
 * most one outline sm button.
 */
export function EmptyState({
  title,
  description,
  action,
  tone = "default",
  className,
  ...props
}: {
  title: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
  tone?: "default" | "error";
  className?: string;
  "data-testid"?: string;
}) {
  return (
    <div
      role={tone === "error" ? "alert" : undefined}
      className={cn(
        "flex flex-col items-center gap-2 px-4 py-7 text-center text-[13.5px] text-muted-foreground",
        className,
      )}
      {...props}
    >
      <LingoCat mood={tone === "error" ? "oops" : "idle"} size={56} label="" className="mb-1" />
      <p className="text-[14.5px] font-semibold text-foreground">{title}</p>
      {description && <p className="max-w-sm">{description}</p>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}

/** Placeholder block laid out like the real content. */
export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden className={cn("animate-pulse rounded-[6px] bg-muted", className)} />;
}
