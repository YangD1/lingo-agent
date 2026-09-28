import type { ComponentProps } from "react";

import { cn } from "@/lib/utils";

/** A styled native <select>: accessible, works without JS, and plenty for short lists. */
export function NativeSelect({ className, ...props }: ComponentProps<"select">) {
  return (
    <select
      className={cn(
        "h-8 rounded-lg border border-input bg-background px-2 text-sm disabled:opacity-50",
        className,
      )}
      {...props}
    />
  );
}
