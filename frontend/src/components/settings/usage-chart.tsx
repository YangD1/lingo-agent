"use client";

import { useFormatter, useTranslations } from "next-intl";
import { Bar, BarChart, CartesianGrid, XAxis, YAxis } from "recharts";

import { type ChartConfig, ChartContainer, ChartTooltip, ChartTooltipContent } from "@/components/ui/chart";
import type { UsageDashboard } from "@/lib/types";

export type ChartMetric = "calls" | "tokens" | "cost";

/** One measure per UTC day: a single series, so no legend; the metric switch names it. */
export function UsageChart({ board, metric }: { board: UsageDashboard; metric: ChartMetric }) {
  const t = useTranslations("settings.usage");
  const format = useFormatter();
  const config = { value: { label: t(`metric.${metric}`), color: "var(--chart-1)" } } satisfies ChartConfig;
  const data = board.series.map((d) => ({
    day: d.day,
    value: metric === "calls" ? d.calls : metric === "tokens" ? d.input_tokens + d.output_tokens : (d.cost ?? 0),
  }));
  const show = (v: number) =>
    metric === "cost"
      ? format.number(v, { style: "currency", currency: board.currency, maximumFractionDigits: 2 })
      : format.number(v, { notation: "compact" });
  return (
    <ChartContainer config={config} className="aspect-auto h-48 w-full" data-testid="usage-chart">
      <BarChart data={data} accessibilityLayer margin={{ left: 4, right: 4, top: 8 }}>
        <CartesianGrid vertical={false} />
        <XAxis
          dataKey="day"
          tickLine={false}
          axisLine={false}
          minTickGap={24}
          tickFormatter={(day: string) => day.slice(5)}
        />
        <YAxis tickLine={false} axisLine={false} width={48} tickFormatter={show} allowDecimals={metric === "cost"} />
        <ChartTooltip
          cursor={{ fill: "var(--muted)" }}
          content={
            <ChartTooltipContent
              labelFormatter={(day) => String(day)}
              formatter={(v) => (
                <div className="flex flex-1 justify-between gap-4 leading-none">
                  <span className="text-muted-foreground">{config.value.label}</span>
                  <span className="font-mono font-medium text-foreground tabular-nums">{show(Number(v))}</span>
                </div>
              )}
            />
          }
        />
        <Bar dataKey="value" fill="var(--color-value)" radius={[4, 4, 0, 0]} maxBarSize={28} isAnimationActive={false} />
      </BarChart>
    </ChartContainer>
  );
}
