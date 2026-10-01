import { cva, type VariantProps } from "class-variance-authority";
import type { ComponentProps } from "react";

import { cn } from "@/lib/utils";

// component-spec §10. The AI colour is deliberately not a variant: it belongs to AiBadge.
const tagVariants = cva(
  "inline-flex h-5 shrink-0 items-center gap-1 rounded-[6px] px-[7px] text-[11.5px] leading-none font-semibold whitespace-nowrap [&_svg]:size-3",
  {
    variants: {
      variant: {
        default: "bg-secondary text-secondary-foreground",
        outline: "border text-muted-foreground font-medium",
        brand: "bg-brand-soft text-brand-soft-foreground",
        success: "bg-[color-mix(in_oklab,var(--success)_13%,var(--card))] text-success",
        warning: "bg-[color-mix(in_oklab,var(--warning)_13%,var(--card))] text-warning",
      },
    },
    defaultVariants: { variant: "default" },
  },
);

export function Tag({
  className,
  variant,
  ...props
}: ComponentProps<"span"> & VariantProps<typeof tagVariants>) {
  return <span className={cn(tagVariants({ variant }), className)} {...props} />;
}

export const CEFR_LEVELS = ["A1", "A2", "B1", "B2", "C1", "C2"] as const;
export type CefrLevel = (typeof CEFR_LEVELS)[number];

const CEFR_COLORS: Record<CefrLevel, string> = {
  A1: "bg-(--cefr-1) text-(--cefr-1-fg)",
  A2: "bg-(--cefr-2) text-(--cefr-2-fg)",
  B1: "bg-(--cefr-3) text-(--cefr-3-fg)",
  B2: "bg-(--cefr-4) text-(--cefr-4-fg)",
  C1: "bg-(--cefr-5) text-(--cefr-5-fg)",
  C2: "bg-(--cefr-6) text-(--cefr-6-fg)",
};

/** A CEFR level with a six-step scale, so the order reads without colour. */
export function CefrTag({ level, className }: { level: CefrLevel; className?: string }) {
  const reached = CEFR_LEVELS.indexOf(level) + 1;
  return (
    <span
      data-testid="cefr-tag"
      className={cn(
        "inline-flex h-5 shrink-0 items-center gap-[5px] rounded-[6px] pr-1.5 pl-[7px] font-mono text-[11.5px] leading-none font-[650] tracking-[0.02em]",
        CEFR_COLORS[level],
        className,
      )}
    >
      {level}
      <span aria-hidden className="inline-flex gap-[1.5px]">
        {CEFR_LEVELS.map((step, i) => (
          <span
            key={step}
            data-filled={i < reached}
            className={cn("h-2 w-0.5 rounded-[1px] bg-current", i < reached ? "opacity-100" : "opacity-25")}
          />
        ))}
      </span>
    </span>
  );
}

export function isCefrLevel(value: string): value is CefrLevel {
  return (CEFR_LEVELS as readonly string[]).includes(value);
}
