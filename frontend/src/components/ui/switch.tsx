"use client";

import { Switch as SwitchPrimitive } from "@base-ui/react/switch";

import { cn } from "@/lib/utils";

/** On/off switch: a pill track whose thumb slides right when on. */
function Switch({
  className,
  size = "default",
  ...props
}: SwitchPrimitive.Root.Props & { size?: "default" | "sm" }) {
  return (
    <SwitchPrimitive.Root
      data-slot="switch"
      className={cn(
        "inline-flex shrink-0 cursor-pointer items-center rounded-full border border-transparent bg-input transition-colors outline-none",
        "focus-visible:ring-3 focus-visible:ring-ring/50 data-checked:bg-primary",
        "data-disabled:cursor-not-allowed data-disabled:opacity-50",
        size === "sm" ? "h-4 w-7" : "h-5 w-9",
        className,
      )}
      {...props}
    >
      <SwitchPrimitive.Thumb
        data-slot="switch-thumb"
        className={cn(
          "pointer-events-none block rounded-full bg-background shadow-sm transition-transform",
          "translate-x-0.5 data-checked:translate-x-[calc(100%+2px)]",
          size === "sm" ? "size-3" : "size-4",
        )}
      />
    </SwitchPrimitive.Root>
  );
}

export { Switch };
