"use client";

import { useFormatter, useTranslations } from "next-intl";

import { cn } from "@/lib/utils";
import { type Day, intensity, weeks } from "@/lib/dashboard";

const SHADES = ["bg-heat-0", "bg-heat-1", "bg-heat-2", "bg-heat-3", "bg-heat-4"] as const;

/**
 * Daily study over the last weeks, one column a week (Monday on top). Recharts has no
 * calendar heatmap, so it is a plain grid; each cell's title gives the numbers.
 */
export function ActivityHeatmap({ days }: { days: Day[] }) {
  const t = useTranslations("dashboard.activity");
  const format = useFormatter();
  const max = Math.max(0, ...days.map((d) => d.reviews + d.turns));
  const describe = (d: Day) =>
    t("cell", {
      date: format.dateTime(new Date(`${d.date}T00:00:00`), { month: "short", day: "numeric" }),
      reviews: d.reviews,
      turns: d.turns,
    });
  return (
    <div className="flex flex-col gap-2">
      <div className="flex gap-1 overflow-x-auto" role="list" aria-label={t("title")}>
        {weeks(days).map((week, w) => (
          <div key={w} className="flex flex-col gap-1">
            {week.map((d, i) =>
              d ? (
                <div
                  key={d.date}
                  role="listitem"
                  title={describe(d)}
                  aria-label={describe(d)}
                  data-level={intensity(d, max)}
                  className={cn("size-3.5 rounded-[3px]", SHADES[intensity(d, max)])}
                />
              ) : (
                <div key={`pad-${i}`} className="size-3.5" aria-hidden />
              ),
            )}
          </div>
        ))}
      </div>
      <div className="flex items-center gap-1 text-xs text-muted-foreground" aria-hidden>
        <span>{t("less")}</span>
        {SHADES.map((shade) => (
          <span key={shade} className={cn("size-3 rounded-[3px]", shade)} />
        ))}
        <span>{t("more")}</span>
      </div>
    </div>
  );
}
