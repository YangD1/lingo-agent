import type { ComponentProps } from "react";

import { cn } from "@/lib/utils";

/**
 * The cat mark from docs/design/lingo-agent-design/logo/logo-mark.svg, drawn inline so it
 * follows the theme: --brand switches to the lighter coral in dark mode.
 */
export function LogoMark({ className, ...props }: ComponentProps<"svg">) {
  return (
    <svg
      viewBox="0 0 64 64"
      aria-hidden
      className={cn("size-6 shrink-0", className)}
      {...props}
    >
      <g fill="var(--brand)" stroke="var(--brand)" strokeLinejoin="round">
        <path strokeWidth="3.4" d="M14.4 14.4L12.8 5.4L18 10.8Z" />
        <path strokeWidth="3.4" d="M29.6 14.4L31.2 5.4L26 10.8Z" />
        <ellipse stroke="none" cx="22" cy="19.2" rx="10.8" ry="10.4" />
        <path
          stroke="none"
          d="M15 23C8.8 30 8.2 43.6 9.6 50.2Q10.4 54 14.6 54H29.4Q33.6 54 34.4 50.2C35.8 43.6 35.2 30 29 23Z"
        />
      </g>
      <path
        d="M31 51.2H42C49 51.2 52.5 46.4 51.5 41.2C50.6 36.8 45.6 35.8 43 38.8"
        fill="none"
        stroke="var(--brand)"
        strokeWidth="5.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path fill="var(--spark)" d="M43 12.5Q43 19 49.5 19Q43 19 43 25.5Q43 19 36.5 19Q43 19 43 12.5Z" />
    </svg>
  );
}

/** Mark plus the product name. The name is always "Lingo Agent" in the UI. */
export function Logo({ className, markClassName }: { className?: string; markClassName?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-2 font-semibold tracking-tight", className)}>
      <LogoMark className={markClassName} />
      Lingo Agent
    </span>
  );
}
