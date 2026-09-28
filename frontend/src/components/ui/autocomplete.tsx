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
};

/** A text input with a searchable suggestion list: for free-form values with known options. */
export function AutocompleteInput({
  value,
  onValueChange,
  items,
  onOpenChange,
  empty,
  className,
  ...inputProps
}: Props) {
  const [typing, setTyping] = useState(false);
  const query = value.trim().toLowerCase();
  const shown = typing && query ? items.filter((i) => i.toLowerCase().includes(query)) : items;
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
          "h-8 w-full min-w-0 rounded-lg border border-input bg-transparent px-2.5 py-1 text-base transition-colors outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 disabled:pointer-events-none disabled:opacity-50 md:text-sm dark:bg-input/30",
          className,
        )}
        {...inputProps}
      />
      <Autocomplete.Portal>
        <Autocomplete.Positioner sideOffset={4} align="start" className="z-50 outline-none">
          <Autocomplete.Popup className="max-h-72 w-(--anchor-width) min-w-48 overflow-y-auto rounded-lg border bg-popover p-1 text-sm text-popover-foreground shadow-md">
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
                  className="cursor-default rounded-md px-2 py-1.5 font-mono select-none data-highlighted:bg-accent data-highlighted:text-accent-foreground"
                >
                  {item}
                </Autocomplete.Item>
              )}
            </Autocomplete.List>
          </Autocomplete.Popup>
        </Autocomplete.Positioner>
      </Autocomplete.Portal>
    </Autocomplete.Root>
  );
}
