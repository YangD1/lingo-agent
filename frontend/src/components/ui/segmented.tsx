"use client";

import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

export type SegmentedOption<T extends string> = {
  value: T;
  label: string;
  /** When set, the option shows only the icon and `label` becomes its accessible name. */
  icon?: ReactNode;
};

/** Segmented control (component-spec §4): a radio group styled as a pill switch. */
export function Segmented<T extends string>({
  value,
  options,
  onChange,
  label,
  size = "default",
  className,
}: {
  value: T | undefined;
  options: SegmentedOption<T>[];
  onChange: (value: T) => void;
  label: string;
  size?: "default" | "sm";
  className?: string;
}) {
  return (
    <div
      role="radiogroup"
      aria-label={label}
      className={cn("inline-flex rounded-md bg-muted p-[3px]", className)}
    >
      {options.map((option) => {
        const checked = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={checked}
            aria-label={option.icon ? option.label : undefined}
            title={option.icon ? option.label : undefined}
            onClick={() => onChange(option.value)}
            className={cn(
              "inline-flex flex-1 items-center justify-center gap-1.5 rounded-sm px-2.5 text-[13px] text-muted-foreground transition-colors outline-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring [&_svg]:size-3.5",
              size === "sm" ? "h-6" : "h-7",
              checked && "bg-card font-semibold text-foreground shadow-(--shadow-lift)",
            )}
          >
            {option.icon ?? option.label}
          </button>
        );
      })}
    </div>
  );
}
