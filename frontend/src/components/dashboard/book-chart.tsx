"use client";

import { useFormatter, useTranslations } from "next-intl";
import { Cell, Label, Pie, PieChart } from "recharts";

import { type ChartConfig, ChartContainer, ChartTooltip, ChartTooltipContent } from "@/components/ui/chart";
import type { Dashboard } from "@/lib/dashboard";

import { ChartLegend } from "./chart-legend";

const PARTS = ["mastered", "learning", "known", "unlearned"] as const;
const COLORS = {
  mastered: "var(--chart-1)",
  learning: "var(--chart-2)",
  known: "var(--chart-4)",
  unlearned: "var(--chart-5)",
} as const;
const SWATCHES = {
  mastered: "bg-chart-1",
  learning: "bg-chart-2",
  known: "bg-chart-4",
  unlearned: "bg-chart-5",
} as const;

/** Share of the book by progress: parts of one whole, so a donut (P1 plan §7.5.1). */
export function BookChart({ book }: { book: NonNullable<Dashboard["book"]> }) {
  const t = useTranslations("dashboard.book");
  const format = useFormatter();
  const config = Object.fromEntries(
    PARTS.map((p) => [p, { label: t(p), color: COLORS[p] }]),
  ) satisfies ChartConfig;
  const data = PARTS.map((p) => ({ part: p, count: book[p], fill: COLORS[p] }));
  const done = book.total ? Math.round((100 * (book.mastered + book.known)) / book.total) : 0;
  return (
    <div className="flex flex-col items-center gap-5 sm:flex-row">
    <ChartContainer config={config} className="aspect-square w-40 shrink-0">
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
                  <tspan x={viewBox.cx} dy="-0.3em" className="fill-foreground text-[22px] font-bold">
                    {done}%
                  </tspan>
                  <tspan x={viewBox.cx} dy="1.7em" className="fill-muted-foreground text-[11px]">
                    {t("center")}
                  </tspan>
                </text>
              );
            }}
          />
        </Pie>
      </PieChart>
    </ChartContainer>
      <ChartLegend
        className="w-full flex-col gap-y-2.5 text-[13px]"
        items={PARTS.map((p) => ({
          key: p,
          label: t(p),
          swatch: SWATCHES[p],
          count: format.number(book[p]),
        }))}
      />
    </div>
  );
}
