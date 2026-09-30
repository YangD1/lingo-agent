"use client";

import { useTranslations } from "next-intl";
import { Bar, BarChart, CartesianGrid, XAxis, YAxis } from "recharts";

import {
  type ChartConfig,
  ChartContainer,
  ChartLegend,
  ChartLegendContent,
  ChartTooltip,
  ChartTooltipContent,
} from "@/components/ui/chart";
import type { Dashboard } from "@/lib/dashboard";
import { CEFR_LEVELS } from "@/lib/learner";

const PARTS = ["mastered", "learning", "weak", "unseen"] as const;
const COLORS = {
  mastered: "var(--chart-1)",
  learning: "var(--chart-2)",
  weak: "var(--chart-3)",
  unseen: "var(--chart-5)",
} as const;

/** Grammar points per level by mastery, stacked (P1 plan §7.5.1). */
export function GrammarChart({ grammar }: { grammar: Dashboard["grammar"] }) {
  const t = useTranslations("dashboard.grammar");
  const config = Object.fromEntries(
    PARTS.map((p) => [p, { label: t(p), color: COLORS[p] }]),
  ) satisfies ChartConfig;
  const data = CEFR_LEVELS.map((level) => ({ level, ...grammar[level] }));
  return (
    <ChartContainer config={config} className="aspect-auto h-64 w-full">
      <BarChart data={data} layout="vertical" margin={{ left: 0, right: 8 }} accessibilityLayer>
        <CartesianGrid horizontal={false} />
        <YAxis dataKey="level" type="category" tickLine={false} axisLine={false} width={28} />
        <XAxis type="number" tickLine={false} axisLine={false} allowDecimals={false} />
        <ChartTooltip content={<ChartTooltipContent />} />
        <ChartLegend itemSorter={null} content={<ChartLegendContent />} />
        {PARTS.map((p, i) => (
          <Bar
            key={p}
            dataKey={p}
            stackId="kc"
            fill={COLORS[p]}
            stroke="var(--card)"
            strokeWidth={1}
            radius={i === PARTS.length - 1 ? [0, 4, 4, 0] : 0}
            isAnimationActive={false}
          />
        ))}
      </BarChart>
    </ChartContainer>
  );
}
