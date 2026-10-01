import { cva, type VariantProps } from "class-variance-authority";
import { XIcon } from "lucide-react";
import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

// In-page banner (component-spec §7): brand for the placement nudge, neutral for practice
// and retest bars, warning for "no model configured".
const calloutVariants = cva(
  "flex items-center gap-3 rounded-lg border py-2.5 pr-3 pl-3.5 text-sm [&>svg]:size-[18px] [&>svg]:shrink-0",
  {
    variants: {
      tone: {
        brand:
          "border-[color-mix(in_oklab,var(--brand)_18%,transparent)] bg-brand-soft [&>svg]:text-brand-soft-foreground",
        neutral: "border-border bg-muted [&>svg]:text-muted-foreground",
        warning:
          "border-[color-mix(in_oklab,var(--warning)_25%,transparent)] bg-[color-mix(in_oklab,var(--warning)_10%,var(--card))] [&>svg]:text-warning",
      },
    },
    defaultVariants: { tone: "neutral" },
  },
);

export function Callout({
  tone,
  icon,
  children,
  action,
  onDismiss,
  dismissLabel,
  className,
  ...props
}: VariantProps<typeof calloutVariants> & {
  icon?: ReactNode;
  children: ReactNode;
  /** Usually a default sm button or link. */
  action?: ReactNode;
  onDismiss?: () => void;
  dismissLabel?: string;
  className?: string;
  "data-testid"?: string;
}) {
  return (
    <div role="status" className={cn(calloutVariants({ tone }), className)} {...props}>
      {icon}
      <div className="min-w-0 flex-1">{children}</div>
      {action}
      {onDismiss && (
        <Button variant="ghost" size="icon-sm" aria-label={dismissLabel} onClick={onDismiss}>
          <XIcon />
        </Button>
      )}
    </div>
  );
}
