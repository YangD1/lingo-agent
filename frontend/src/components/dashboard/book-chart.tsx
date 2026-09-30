"use client";

import { useTranslations } from "next-intl";
import { Cell, Label, Pie, PieChart } from "recharts";

import {
  type ChartConfig,
  ChartContainer,
  ChartLegend,
  ChartLegendContent,
  ChartTooltip,
  ChartTooltipContent,
} from "@/components/ui/chart";
import type { Dashboard } from "@/lib/dashboard";

const PARTS = ["mastered", "learning", "known", "unlearned"] as const;
const COLORS = {
  mastered: "var(--chart-1)",
  learning: "var(--chart-2)",
  known: "var(--chart-4)",
  unlearned: "var(--chart-5)",
} as const;

/** Share of the book by progress: parts of one whole, so a donut (P1 plan §7.5.1). */
export function BookChart({ book }: { book: NonNullable<Dashboard["book"]> }) {
  const t = useTranslations("dashboard.book");
  const config = Object.fromEntries(
    PARTS.map((p) => [p, { label: t(p), color: COLORS[p] }]),
  ) satisfies ChartConfig;
  const data = PARTS.map((p) => ({ part: p, count: book[p], fill: COLORS[p] }));
  const done = book.total ? Math.round((100 * (book.mastered + book.known)) / book.total) : 0;
  return (
    <ChartContainer config={config} className="mx-auto aspect-square max-h-64 w-full">
      <PieChart accessibilityLayer>
        <ChartTooltip content={<ChartTooltipContent nameKey="part" hideLabel />} />
        <Pie
          data={data}
          dataKey="count"
          nameKey="part"
          innerRadius="58%"
          outerRadius="85%"
          stroke="var(--card)"
          strokeWidth={2}
          isAnimationActive={false}
        >
          {data.map((d) => (
            <Cell key={d.part} fill={d.fill} />
          ))}
          <Label
            content={({ viewBox }) => {
              if (!viewBox || !("cx" in viewBox)) return null;
              return (
                <text x={viewBox.cx} y={viewBox.cy} textAnchor="middle" dominantBaseline="middle">
                  <tspan x={viewBox.cx} dy="-0.3em" className="fill-foreground text-2xl font-semibold">
                    {done}%
                  </tspan>
                  <tspan x={viewBox.cx} dy="1.6em" className="fill-muted-foreground text-xs">
                    {t("center")}
                  </tspan>
                </text>
              );
            }}
          />
        </Pie>
        <ChartLegend itemSorter={null} content={<ChartLegendContent nameKey="part" />} />
      </PieChart>
    </ChartContainer>
  );
}
