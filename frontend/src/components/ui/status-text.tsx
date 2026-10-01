import { CircleAlertIcon, CircleCheckIcon, TriangleAlertIcon } from "lucide-react";
import type { ComponentProps } from "react";

import { cn } from "@/lib/utils";

const TONES = {
  success: { icon: CircleCheckIcon, className: "text-success" },
  warning: { icon: TriangleAlertIcon, className: "text-warning" },
  error: { icon: CircleAlertIcon, className: "text-destructive" },
} as const;

/** Inline status line (component-spec §8): "Saved.", a warning, or an error. */
export function StatusText({
  tone,
  className,
  children,
  ...props
}: ComponentProps<"p"> & { tone: keyof typeof TONES }) {
  const { icon: Icon, className: color } = TONES[tone];
  return (
    <p className={cn("flex items-start gap-1.5 text-[13px] leading-5", color, className)} {...props}>
      <Icon aria-hidden className="mt-[2.5px] size-[15px] shrink-0" />
      <span>{children}</span>
    </p>
  );
}
