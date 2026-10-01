import { cn } from "@/lib/utils";

/**
 * Progress bar (component-spec §11). Always pair it with visible text such as
 * "62% · learning"; the bar alone is decoration, so it is hidden from screen readers.
 */
export function ProgressBar({
  value,
  className,
  barClassName = "bg-primary",
  thin = false,
}: {
  /** 0–1. */
  value: number;
  className?: string;
  /** Fill colour, e.g. bg-chart-1 for mastered. */
  barClassName?: string;
  thin?: boolean;
}) {
  const pct = Math.max(0, Math.min(1, value)) * 100;
  return (
    <div aria-hidden className={cn("flex w-full overflow-hidden rounded-full bg-muted", thin ? "h-1" : "h-1.5", className)}>
      <span className={cn("block h-full rounded-full", barClassName)} style={{ width: `${pct}%` }} />
    </div>
  );
}

/** Stacked bar: segments are separated by a 1.5px gap in the card colour. */
export function StackedBar({
  segments,
  className,
}: {
  segments: { value: number; className: string; key: string }[];
  className?: string;
}) {
  const total = segments.reduce((sum, s) => sum + s.value, 0);
  return (
    <div aria-hidden className={cn("flex h-2 w-full overflow-hidden rounded-full bg-muted", className)}>
      {total > 0 &&
        segments
          .filter((s) => s.value > 0)
          .map((s) => (
            <span
              key={s.key}
              className={cn("block h-full not-first:border-l-[1.5px] not-first:border-card", s.className)}
              style={{ width: `${(s.value / total) * 100}%` }}
            />
          ))}
    </div>
  );
}
