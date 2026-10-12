"use client";

import { useFormatter, useTranslations } from "next-intl";

import { Input } from "@/components/ui/input";
import { CAPABILITIES, type Capability, type Limit, type QuotaUsage, type Quotas, UNITS } from "@/lib/org";
import { cn } from "@/lib/utils";

/** A cap being typed: "" is no cap. */
export type LimitDraft = { daily: string; monthly: string };
export type QuotasDraft = Record<Capability, LimitDraft>;

// The backend takes any non-negative integer; this keeps typos like an extra 0 visible.
const MAX_CAP = 1_000_000_000;

export function toDraft(quotas: Quotas): QuotasDraft {
  const cap = (v: number | null) => (v === null ? "" : String(v));
  return Object.fromEntries(
    CAPABILITIES.map((c) => [c, { daily: cap(quotas[c].daily), monthly: cap(quotas[c].monthly) }]),
  ) as QuotasDraft;
}

function parseCap(draft: string): number | null | undefined {
  if (draft.trim() === "") return null;
  const value = Number(draft);
  return Number.isInteger(value) && value >= 0 && value <= MAX_CAP ? value : undefined;
}

/** The quotas typed, or null while any cap is invalid. */
export function fromDraft(draft: QuotasDraft): Quotas | null {
  const out: Partial<Quotas> = {};
  for (const c of CAPABILITIES) {
    const daily = parseCap(draft[c].daily);
    const monthly = parseCap(draft[c].monthly);
    if (daily === undefined || monthly === undefined) return null;
    out[c] = { daily, monthly };
  }
  return out as Quotas;
}

/** Daily and monthly caps per capability; an empty box is no cap, 0 turns it off. */
export function QuotaFields({
  idPrefix,
  draft,
  onChange,
}: {
  idPrefix: string;
  draft: QuotasDraft;
  onChange: (draft: QuotasDraft) => void;
}) {
  const t = useTranslations("settings.org");
  return (
    <div className="overflow-x-auto rounded-lg border">
      <table className="w-full text-[13px]">
        <thead className="bg-muted/60 text-left text-xs text-muted-foreground">
          <tr>
            <th className="px-3 py-2 font-medium">{t("capability")}</th>
            <th className="px-3 py-2 font-medium">{t("daily")}</th>
            <th className="px-3 py-2 font-medium">{t("monthly")}</th>
          </tr>
        </thead>
        <tbody>
          {CAPABILITIES.map((c) => (
            <tr key={c} className="border-t">
              <td className="px-3 py-2">
                {t(`capabilities.${c}`)}
                <span className="ml-1 text-xs text-muted-foreground">({t(`units.${UNITS[c]}`)})</span>
              </td>
              {(["daily", "monthly"] as const).map((period) => (
                <td key={period} className="px-3 py-1.5">
                  <Input
                    id={`${idPrefix}-${c}-${period}`}
                    aria-label={`${t(`capabilities.${c}`)} · ${t(period)}`}
                    type="number"
                    inputMode="numeric"
                    min={0}
                    placeholder={t("noCap")}
                    value={draft[c][period]}
                    aria-invalid={parseCap(draft[c][period]) === undefined}
                    onChange={(e) => onChange({ ...draft, [c]: { ...draft[c], [period]: e.target.value } })}
                    className="h-8 w-32"
                  />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      <p className="border-t px-3 py-2 text-xs text-muted-foreground">{t("capsHint")}</p>
    </div>
  );
}

/** Each capability's use today and this month against its caps. */
export function QuotaUsageTable({
  quotas,
  usage,
  label,
}: {
  quotas: Quotas;
  usage?: QuotaUsage;
  label: string;
}) {
  const t = useTranslations("settings.org");
  const format = useFormatter();
  const n = (v: number) => format.number(v, { maximumFractionDigits: 1 });
  const cell = (used: number | undefined, cap: number | null) => {
    if (cap === 0) return <span className="text-muted-foreground">{t("off")}</span>;
    const capText = cap === null ? t("noCap") : n(cap);
    if (used === undefined) return capText;
    return (
      <span className={cn(cap !== null && used >= cap && "text-destructive")}>
        {n(used)} / {capText}
      </span>
    );
  };
  return (
    <div className="overflow-x-auto rounded-lg border">
      <table className="w-full text-[13px] whitespace-nowrap" aria-label={label}>
        <thead className="bg-muted/60 text-left text-xs text-muted-foreground">
          <tr>
            <th className="px-3 py-2 font-medium">{t("capability")}</th>
            <th className="px-3 py-2 text-right font-medium">{usage ? t("today") : t("daily")}</th>
            <th className="px-3 py-2 text-right font-medium">{usage ? t("thisMonth") : t("monthly")}</th>
          </tr>
        </thead>
        <tbody className="font-mono">
          {CAPABILITIES.map((c) => {
            const limit: Limit = quotas[c];
            return (
              <tr key={c} className="border-t">
                <td className="px-3 py-2 font-sans">
                  {t(`capabilities.${c}`)}
                  <span className="ml-1 text-xs text-muted-foreground">({t(`units.${UNITS[c]}`)})</span>
                </td>
                <td className="px-3 py-2 text-right">{cell(usage?.[c].day, limit.daily)}</td>
                <td className="px-3 py-2 text-right">{cell(usage?.[c].month, limit.monthly)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
