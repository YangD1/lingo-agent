import type { ReactNode } from "react";

import { LingoCat } from "@/components/brand/lingo-cat";
import { cn } from "@/lib/utils";

/**
 * One-line error with the small oops cat in front (task 29). For a whole area that failed to
 * load, use `EmptyState tone="error"` instead.
 */
export function ErrorText({
  children,
  size = "sm",
  className,
}: {
  children: ReactNode;
  size?: "sm" | "xs";
  className?: string;
}) {
  return (
    <p
      role="alert"
      className={cn(
        "flex items-start gap-1.5 text-destructive",
        size === "sm" ? "text-sm" : "text-xs",
        className,
      )}
    >
      <LingoCat mood="oops" size={size === "sm" ? 20 : 16} label="" className="-mt-px" />
      <span className="min-w-0">{children}</span>
    </p>
  );
}
