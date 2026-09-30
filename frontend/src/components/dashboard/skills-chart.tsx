"use client";

import { useTranslations } from "next-intl";
import { Bar, BarChart, CartesianGrid, LabelList, XAxis, YAxis } from "recharts";

import { type ChartConfig, ChartContainer } from "@/components/ui/chart";
import type { SkillPoint } from "@/lib/dashboard";
import { CEFR_LEVELS } from "@/lib/learner";

// Level i covers [i, i + 1): gridlines at the boundaries, level names in the middle.
const BOUNDARIES = [0, 1, 2, 3, 4, 5, 6];
const MIDDLES = CEFR_LEVELS.map((_, i) => i + 0.5);
const MIN_BAR = 0.08;

/** Measured skills on one CEFR scale (Q17d); each bar is labelled with its level. */
export function SkillsChart({
  skills,
  name,
}: {
  skills: SkillPoint[];
  name: (skill: string) => string;
}) {
  const t = useTranslations("dashboard.skills");
  const config = { position: { label: t("title"), color: "var(--chart-1)" } } satisfies ChartConfig;
  // A learner at the very bottom of A1 sits at 0; keep a sliver so the bar still shows.
  const data = skills.map((s) => ({
    skill: name(s.skill),
    position: Math.max(s.position ?? 0, MIN_BAR),
    cefr: s.cefr,
  }));
  return (
    <ChartContainer
      config={config}
      className="aspect-auto w-full"
      style={{ height: 48 + 40 * data.length }}
      role="img"
      aria-label={data.map((d) => `${d.skill} ${d.cefr ?? ""}`).join(", ")}
    >
      <BarChart data={data} layout="vertical" margin={{ left: 0, right: 32 }}>
        <CartesianGrid horizontal={false} />
        <XAxis
          type="number"
          domain={[0, 6]}
          ticks={MIDDLES}
          tickFormatter={(v: number) => CEFR_LEVELS[Math.floor(v)] ?? ""}
          tickLine={false}
          axisLine={false}
        />
        <XAxis xAxisId="grid" type="number" domain={[0, 6]} ticks={BOUNDARIES} hide />
        <YAxis dataKey="skill" type="category" tickLine={false} axisLine={false} width={40} />
        <Bar
          dataKey="position"
          fill="var(--chart-1)"
          radius={[0, 4, 4, 0]}
          barSize={20}
          isAnimationActive={false}
        >
          <LabelList dataKey="cefr" position="right" className="fill-foreground" fontSize={12} />
        </Bar>
      </BarChart>
    </ChartContainer>
  );
}
