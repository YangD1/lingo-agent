"use client";

import { useRouter } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";
import { Bar, BarChart, LabelList, XAxis, YAxis } from "recharts";

import { type ChartConfig, ChartContainer } from "@/components/ui/chart";
import type { CommonError } from "@/lib/dashboard";
import { kcName, learnerHref } from "@/lib/learner";

/** The most frequent recent mistakes; a bar opens its grammar point (P1 plan §7.5.1). */
export function ErrorsChart({ errors }: { errors: CommonError[] }) {
  const t = useTranslations("dashboard.errors");
  const locale = useLocale();
  const router = useRouter();
  const config = { mistakes: { label: t("title"), color: "var(--chart-3)" } } satisfies ChartConfig;
  const data = errors.map((e) => ({ id: e.kc_id, name: kcName(e, locale), mistakes: e.mistakes }));
  return (
    <ChartContainer
      config={config}
      className="aspect-auto w-full"
      style={{ height: 24 + 36 * data.length }}
      aria-hidden
    >
      <BarChart data={data} layout="vertical" margin={{ left: 0, right: 24 }}>
        <XAxis type="number" hide allowDecimals={false} />
        <YAxis
          dataKey="name"
          type="category"
          tickLine={false}
          axisLine={false}
          width={120}
          tickFormatter={(v: string) => (v.length > 14 ? `${v.slice(0, 13)}…` : v)}
        />
        <Bar
          dataKey="mistakes"
          fill="var(--chart-3)"
          radius={[0, 4, 4, 0]}
          barSize={18}
          className="cursor-pointer"
          isAnimationActive={false}
          onClick={(entry: { payload?: { id: string } }) => {
            if (entry.payload) router.push(learnerHref(entry.payload.id));
          }}
        >
          <LabelList dataKey="mistakes" position="right" className="fill-foreground" fontSize={12} />
        </Bar>
      </BarChart>
    </ChartContainer>
  );
}
