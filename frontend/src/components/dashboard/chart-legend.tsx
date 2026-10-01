import { cn } from "@/lib/utils";

/** Colour key for a chart: a square swatch and a label, plus an optional count on the right. */
export function ChartLegend({
  items,
  className,
}: {
  items: { key: string; label: string; swatch: string; count?: string }[];
  className?: string;
}) {
  return (
    <ul aria-hidden className={cn("flex flex-wrap gap-x-3.5 gap-y-1.5 text-xs text-muted-foreground", className)}>
      {items.map((item) => (
        <li key={item.key} className="flex items-center gap-1.5">
          <span className={cn("size-2.5 shrink-0 rounded-[3px]", item.swatch)} />
          <span className="flex-1">{item.label}</span>
          {item.count !== undefined && (
            <span className="font-mono text-foreground tabular-nums">{item.count}</span>
          )}
        </li>
      ))}
    </ul>
  );
}
