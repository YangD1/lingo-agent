"use client";

import { useLocale } from "next-intl";

import type { CommonError } from "@/lib/dashboard";
import { kcName } from "@/lib/learner";

/**
 * The most frequent recent mistakes as bars (P1 plan §7.5.1). The list under it has the
 * same points as links, so the bars are hidden from screen readers.
 */
export function ErrorsChart({ errors }: { errors: CommonError[] }) {
  const locale = useLocale();
  const max = Math.max(1, ...errors.map((e) => e.mistakes));
  return (
    <div aria-hidden className="grid grid-cols-[minmax(0,7.5rem)_1fr] items-center gap-x-3 gap-y-2 text-xs">
      {errors.map((e) => (
        <div key={e.kc_id} className="contents">
          <span className="truncate">{kcName(e, locale)}</span>
          <div className="flex items-center gap-1.5">
            <span
              className="h-2.5 rounded-full bg-chart-3"
              style={{ width: `${(e.mistakes / max) * 90}%` }}
            />
            <span className="font-mono text-[11px] tabular-nums">{e.mistakes}</span>
          </div>
        </div>
      ))}
    </div>
  );
}
