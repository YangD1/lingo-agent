"use client";

import { useTranslations } from "next-intl";

import { StackedBar } from "@/components/ui/progress";
import type { Dashboard } from "@/lib/dashboard";
import { CEFR_LEVELS } from "@/lib/learner";

import { ChartLegend } from "./chart-legend";

const PARTS = ["mastered", "learning", "weak", "unseen"] as const;
// component-spec §11: mastered chart-1, learning chart-2, weak chart-3, unseen chart-5.
const COLORS = {
  mastered: "bg-chart-1",
  learning: "bg-chart-2",
  weak: "bg-chart-3",
  unseen: "bg-chart-5",
} as const;

/**
 * Grammar points per level by mastery, one stacked bar a level (P1 plan §7.5.1). The table
 * under it carries the numbers, so the bars are decoration for screen readers.
 */
export function GrammarChart({ grammar }: { grammar: Dashboard["grammar"] }) {
  const t = useTranslations("dashboard.grammar");
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-col gap-2.5">
        {CEFR_LEVELS.map((level) => (
          <div
            key={level}
            data-testid="grammar-row"
            className="grid grid-cols-[28px_1fr] items-center gap-2 font-mono text-xs"
          >
            <span className="text-muted-foreground">{level}</span>
            <StackedBar
              className="h-2.5"
              segments={PARTS.map((p) => ({ key: p, value: grammar[level][p], className: COLORS[p] }))}
            />
          </div>
        ))}
      </div>
      <ChartLegend
        items={PARTS.map((p) => ({ key: p, label: t(p), swatch: COLORS[p] }))}
      />
    </div>
  );
}
