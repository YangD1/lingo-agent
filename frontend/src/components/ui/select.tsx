"use client";

import { Select as SelectPrimitive } from "@base-ui/react/select";
import { CheckIcon, ChevronDownIcon } from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

export type SelectOption<V extends string | number> = {
  value: V;
  label: ReactNode;
  /** Shown before the label, in the list and on the trigger (e.g. a CEFR colour dot). */
  marker?: ReactNode;
  /** Muted text at the end of the row in the list only (e.g. a count). */
  hint?: ReactNode;
  disabled?: boolean;
};

/**
 * Dropdown on base-ui Select (task 73.2, Q73b): keyboard, typeahead and screen readers
 * come from base-ui; the list opens below the trigger instead of over it. `className`
 * goes on the trigger so callers can size it in a flex row. With `name` it also submits
 * through a hidden input, so it works in a plain `<form>`.
 */
export function Select<V extends string | number>({
  options,
  value,
  defaultValue,
  onValueChange,
  id,
  name,
  disabled,
  placeholder,
  className,
  size = "default",
  "aria-label": ariaLabel,
  title,
}: {
  options: SelectOption<V>[];
  value?: V;
  defaultValue?: V;
  onValueChange?: (value: V) => void;
  /** Goes on the trigger, so a `<Label htmlFor>` names it. */
  id?: string;
  name?: string;
  disabled?: boolean;
  placeholder?: ReactNode;
  className?: string;
  size?: "default" | "sm";
  "aria-label"?: string;
  title?: string;
}) {
  return (
    <SelectPrimitive.Root<V>
      items={options}
      value={value}
      defaultValue={defaultValue}
      onValueChange={(next) => {
        if (next !== null) onValueChange?.(next);
      }}
      name={name}
      disabled={disabled}
    >
      <SelectPrimitive.Trigger
        id={id}
        aria-label={ariaLabel}
        title={title}
        data-slot="select-trigger"
        className={cn(
          "flex w-full min-w-0 items-center gap-2 rounded-md border border-input bg-card pr-2.5 pl-3 text-left text-sm shadow-(--shadow-field) transition-colors outline-none select-none hover:border-[color-mix(in_oklab,var(--input)_70%,var(--foreground))] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring data-disabled:opacity-45 data-popup-open:border-ring",
          size === "sm" ? "h-8" : "h-10 md:h-9",
          className,
        )}
      >
        <SelectPrimitive.Value className="flex min-w-0 flex-1 items-center gap-2 truncate data-placeholder:text-muted-foreground">
          {(current: V | null) => {
            const option = options.find((o) => o.value === current);
            if (!option) return placeholder ?? null;
            return (
              <>
                {option.marker}
                <span className="truncate">{option.label}</span>
              </>
            );
          }}
        </SelectPrimitive.Value>
        <SelectPrimitive.Icon className="flex shrink-0 text-muted-foreground transition-transform in-data-popup-open:rotate-180">
          <ChevronDownIcon aria-hidden className="size-4" />
        </SelectPrimitive.Icon>
      </SelectPrimitive.Trigger>
      <SelectPrimitive.Portal>
        <SelectPrimitive.Positioner
          alignItemWithTrigger={false}
          sideOffset={6}
          className="isolate z-50 outline-none"
        >
          <SelectPrimitive.Popup
            data-slot="select-content"
            className="glass-pop min-w-(--anchor-width) origin-(--transform-origin) rounded-lg border p-1 text-sm text-popover-foreground outline-none data-open:animate-in data-open:fade-in-0 data-open:zoom-in-95 data-closed:animate-out data-closed:fade-out-0 data-closed:zoom-out-95"
          >
            <SelectPrimitive.List className="max-h-[min(var(--available-height),18rem)] overflow-y-auto">
              {options.map((option) => (
                <SelectPrimitive.Item
                  key={String(option.value)}
                  value={option.value}
                  disabled={option.disabled}
                  className="grid cursor-default grid-cols-[1rem_minmax(0,1fr)_auto] items-center gap-2 rounded-md py-1.5 pr-2.5 pl-2 outline-none select-none data-disabled:opacity-45 data-highlighted:bg-accent data-selected:font-semibold data-selected:text-brand-soft-foreground"
                >
                  <SelectPrimitive.ItemIndicator className="col-start-1 flex text-primary">
                    <CheckIcon aria-hidden className="size-4" />
                  </SelectPrimitive.ItemIndicator>
                  <SelectPrimitive.ItemText className="col-start-2 flex min-w-0 items-center gap-2">
                    {option.marker}
                    <span className="truncate">{option.label}</span>
                  </SelectPrimitive.ItemText>
                  {option.hint != null && (
                    <span className="col-start-3 text-xs font-normal text-muted-foreground tabular-nums">
                      {option.hint}
                    </span>
                  )}
                </SelectPrimitive.Item>
              ))}
            </SelectPrimitive.List>
          </SelectPrimitive.Popup>
        </SelectPrimitive.Positioner>
      </SelectPrimitive.Portal>
    </SelectPrimitive.Root>
  );
}
