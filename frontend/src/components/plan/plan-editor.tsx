"use client";

import { Minus, Plus } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { useId } from "react";

import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import {
  choiceMinutes,
  clampChoice,
  type Estimates,
  type ItemKind,
  ITEM_KINDS,
  type PlanChoice,
  type PlanLimits,
} from "@/lib/plan";

type Counted = "review" | "new_words";
type Switched = "practice" | "reading" | "writing";
const COUNTED = new Set<ItemKind>(["review", "new_words"]);
/** How much a +/- press changes a count. */
const STEP: Record<Counted, number> = { review: 5, new_words: 1 };

/** One line per item: what to do, with its count. */
export function useItemLabel() {
  const t = useTranslations("plan.items");
  const locale = useLocale();
  return (
    kind: ItemKind,
    count: number | null,
    kc?: { name_en: string; name_zh: string } | null,
  ): string => {
    if (kind === "practice" && kc)
      return t("practiceKc", { kc: locale.startsWith("zh") ? kc.name_zh : kc.name_en });
    return t(kind, { n: count ?? 0 });
  };
}

/** Minutes, rounded for reading ("about 9 min"). */
export const roundMinutes = (n: number) => Math.max(0, Math.round(n));

/**
 * Adjust a plan before confirming it (Q48c): counts with -/+ within what is open today,
 * switches for the one-off items, and the estimated total as it changes.
 */
export function PlanEditor({
  choice,
  limits,
  estimates,
  onChange,
  disabled = false,
}: {
  choice: PlanChoice;
  limits: PlanLimits;
  estimates: Estimates;
  onChange: (choice: PlanChoice) => void;
  disabled?: boolean;
}) {
  const t = useTranslations("plan");
  const set = (patch: Partial<PlanChoice>) => onChange(clampChoice({ ...choice, ...patch }, limits));
  const max: Record<Counted, number> = {
    review: Math.min(limits.reviews_due, limits.max_count),
    new_words: Math.min(limits.new_left, limits.max_count),
  };
  const available: Record<Switched, boolean> = {
    practice: limits.practice,
    reading: limits.reading,
    writing: true,
  };
  return (
    <div className="flex flex-col gap-2" data-testid="plan-editor">
      <ul className="flex flex-col divide-y rounded-lg border text-[13px]">
        {ITEM_KINDS.map((kind) =>
          COUNTED.has(kind) ? (
            <CountRow
              key={kind}
              kind={kind as Counted}
              value={choice[kind as Counted]}
              max={max[kind as Counted]}
              minutes={choice[kind as Counted] * estimates[kind]}
              disabled={disabled}
              onChange={(n) => set({ [kind]: n })}
            />
          ) : (
            <SwitchRow
              key={kind}
              kind={kind as Switched}
              on={choice[kind as Switched]}
              available={available[kind as Switched]}
              minutes={estimates[kind]}
              disabled={disabled}
              onChange={(on) => set({ [kind]: on })}
            />
          ),
        )}
      </ul>
      <p className="text-xs text-muted-foreground" data-testid="plan-total">
        {t("total", { n: roundMinutes(choiceMinutes(choice, estimates)) })}
      </p>
    </div>
  );
}

function CountRow({
  kind,
  value,
  max,
  minutes,
  disabled,
  onChange,
}: {
  kind: Counted;
  value: number;
  max: number;
  minutes: number;
  disabled: boolean;
  onChange: (n: number) => void;
}) {
  const t = useTranslations("plan");
  const label = useItemLabel();
  return (
    <li className="flex min-h-11 items-center gap-2 px-3 py-1.5" data-testid={`plan-row-${kind}`}>
      <span className="min-w-0 flex-1">
        <span className="block font-medium">{label(kind, value)}</span>
        <span className="block text-xs text-muted-foreground">
          {max === 0 ? t(`none.${kind}`) : t("upTo", { n: max })}
        </span>
      </span>
      {value > 0 && (
        <span className="shrink-0 text-xs text-muted-foreground tabular-nums">
          {t("minutes", { n: roundMinutes(minutes) })}
        </span>
      )}
      <span className="flex shrink-0 items-center gap-1">
        <Button
          size="icon-sm"
          variant="outline"
          aria-label={t("less", { item: label(kind, value) })}
          disabled={disabled || value <= 0}
          onClick={() => onChange(value - STEP[kind])}
        >
          <Minus />
        </Button>
        <Button
          size="icon-sm"
          variant="outline"
          aria-label={t("more", { item: label(kind, value) })}
          disabled={disabled || value >= max}
          onClick={() => onChange(value + STEP[kind])}
        >
          <Plus />
        </Button>
      </span>
    </li>
  );
}

function SwitchRow({
  kind,
  on,
  available,
  minutes,
  disabled,
  onChange,
}: {
  kind: Switched;
  on: boolean;
  available: boolean;
  minutes: number;
  disabled: boolean;
  onChange: (on: boolean) => void;
}) {
  const t = useTranslations("plan");
  const label = useItemLabel();
  const id = useId();
  return (
    <li className="flex min-h-11 items-center gap-2 px-3 py-1.5" data-testid={`plan-row-${kind}`}>
      <label htmlFor={id} className="min-w-0 flex-1">
        <span className="block font-medium">{label(kind, null)}</span>
        {!available && (
          <span className="block text-xs text-muted-foreground">{t(`none.${kind}`)}</span>
        )}
      </label>
      {on && (
        <span className="shrink-0 text-xs text-muted-foreground tabular-nums">
          {t("minutes", { n: roundMinutes(minutes) })}
        </span>
      )}
      <Switch
        id={id}
        checked={on}
        disabled={disabled || !available}
        onCheckedChange={(checked) => onChange(checked)}
      />
    </li>
  );
}
