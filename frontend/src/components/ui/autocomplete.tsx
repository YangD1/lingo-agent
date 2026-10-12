"use client";

import { Autocomplete } from "@base-ui/react/autocomplete";
import { type ComponentProps, type ReactNode, useState } from "react";

import { cn } from "@/lib/utils";

type Props = Omit<ComponentProps<"input">, "value" | "defaultValue" | "onChange"> & {
  value: string;
  onValueChange: (value: string) => void;
  /**
   * Suggestions, filtered by what's typed since the list opened (so an input that already
   * holds a value still offers every option). Any other text is still a valid value.
   */
  items: readonly string[];
  onOpenChange?: (open: boolean) => void;
  /** Shown in the popup when nothing matches (or while `items` is still loading). */
  empty?: ReactNode;
  /** Says what an item is, next to it in the list; also matched when filtering. */
  describe?: (item: string) => string;
};

/** A text input with a searchable suggestion list: for free-form values with known options. */
export function AutocompleteInput({
  value,
  onValueChange,
  items,
  onOpenChange,
  empty,
  describe,
  className,
  ...inputProps
}: Props) {
  const [typing, setTyping] = useState(false);
  const query = value.trim().toLowerCase();
  const matches = (i: string) =>
    i.toLowerCase().includes(query) || (describe?.(i).toLowerCase().includes(query) ?? false);
  const shown = typing && query ? items.filter(matches) : items;
  return (
    <Autocomplete.Root
      items={items}
      filteredItems={shown}
      value={value}
      onValueChange={(v, details) => {
        if (details.reason === "input-change") setTyping(true);
        onValueChange(v);
      }}
      onOpenChange={(open) => {
        if (open) setTyping(false);
        onOpenChange?.(open);
      }}
      openOnInputClick
    >
      <Autocomplete.Input
        className={cn(
          "h-10 w-full min-w-0 rounded-md border border-input bg-card px-3 py-1 text-base transition-colors outline-none placeholder:text-muted-foreground/85 hover:border-[color-mix(in_oklab,var(--input)_70%,var(--foreground))] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring disabled:pointer-events-none disabled:opacity-45 md:h-9 md:text-sm",
          className,
        )}
        {...inputProps}
      />
      <Autocomplete.Portal>
        <Autocomplete.Positioner sideOffset={4} align="start" className="z-50 outline-none">
          <Autocomplete.Popup className="max-h-72 w-(--anchor-width) min-w-48 overflow-y-auto rounded-lg border bg-popover p-1 text-sm text-popover-foreground shadow-(--shadow-pop)">
            {empty && (
              <Autocomplete.Empty className="px-2 py-1.5 text-muted-foreground empty:hidden">
                {empty}
              </Autocomplete.Empty>
            )}
            <Autocomplete.List>
              {(item: string) => (
                <Autocomplete.Item
                  key={item}
                  value={item}
                  className="flex min-h-8 cursor-default flex-wrap items-center gap-x-2 rounded-sm px-2 py-1 font-mono select-none data-highlighted:bg-accent data-highlighted:text-accent-foreground"
                >
                  {item}
                  {describe && (
                    <span className="font-sans text-xs text-muted-foreground">{describe(item)}</span>
                  )}
                </Autocomplete.Item>
              )}
            </Autocomplete.List>
          </Autocomplete.Popup>
        </Autocomplete.Positioner>
      </Autocomplete.Portal>
    </Autocomplete.Root>
  );
}
