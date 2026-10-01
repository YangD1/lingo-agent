"use client";

import { useTranslations } from "next-intl";

import { CEFR_LEVELS } from "@/lib/learner";

/** A learner at the very bottom of A1 sits at 0; keep a sliver so the bar still shows. */
const MIN_BAR = 0.08;

export type SkillRow = {
  skill: string;
  label: string;
  /** 0–6 on the A1–C2 scale; null when not assessed. */
  position: number | null;
  cefr: string | null;
};

/** Every skill on one CEFR scale (Q17d); measured ones get a bar labelled with the level. */
export function SkillsChart({ rows }: { rows: SkillRow[] }) {
  const t = useTranslations("dashboard.skills");
  return (
    <div
      role="img"
      aria-label={rows
        .map((r) => `${r.label} ${r.position === null ? t("notAssessed") : (r.cefr ?? "")}`)
        .join(", ")}
      className="grid grid-cols-[44px_1fr] items-center gap-x-2 gap-y-2 text-[13px]"
    >
      <span />
      <div className="grid grid-cols-6 font-mono text-[11px] text-muted-foreground">
        {CEFR_LEVELS.map((level) => (
          <span key={level} className="pl-1">
            {level}
          </span>
        ))}
      </div>
      {rows.map((r) => (
        <SkillBar key={r.skill} row={r} />
      ))}
    </div>
  );
}

function SkillBar({ row }: { row: SkillRow }) {
  const t = useTranslations("dashboard.skills");
  return (
    <>
      <span>{row.label}</span>
      {row.position === null ? (
        <span className="text-xs text-muted-foreground">{t("notAssessed")}</span>
      ) : (
        <div className="flex items-center gap-1.5">
          <span
            data-testid="skill-bar"
            className="h-3 rounded-r-[4px] bg-chart-1"
            style={{ width: `${(Math.max(row.position, MIN_BAR) / 6) * 100}%` }}
          />
          <span className="font-mono text-[11px] font-semibold">{row.cefr}</span>
        </div>
      )}
    </>
  );
}
