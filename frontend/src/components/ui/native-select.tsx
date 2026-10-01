import { ChevronDownIcon } from "lucide-react";
import type { ComponentProps } from "react";

import { cn } from "@/lib/utils";

/**
 * A styled native <select>: accessible, works without JS, and plenty for short lists.
 * `className` goes on the wrapper so callers can size it in a flex row.
 */
export function NativeSelect({ className, ...props }: ComponentProps<"select">) {
  return (
    <span className={cn("relative inline-flex", className)}>
      <select
        className="h-10 w-full appearance-none rounded-md border border-input bg-card pr-8 pl-3 text-sm transition-colors outline-none hover:border-[color-mix(in_oklab,var(--input)_70%,var(--foreground))] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring disabled:opacity-45 md:h-9"
        {...props}
      />
      <ChevronDownIcon
        aria-hidden
        className="pointer-events-none absolute top-1/2 right-2.5 size-4 -translate-y-1/2 text-muted-foreground"
      />
    </span>
  );
}
