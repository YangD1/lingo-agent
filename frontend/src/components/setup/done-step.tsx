"use client";

import { ArrowLeftIcon, ArrowRightIcon, CheckIcon, CircleDashedIcon } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { SETUP_STEPS, STEP_HOMES, type SetupSteps } from "@/lib/setup";

import { LeaveLink } from "./step-frame";

/**
 * The summary (ADR 0042 §2): what is set up, where to set up the rest later, and the
 * advanced settings the guide leaves out.
 */
export function DoneStep({
  steps,
  onBack,
  onFinish,
}: {
  steps: SetupSteps;
  onBack: () => void;
  /** Finishes the guide, then opens `to` (the dashboard by default). */
  onFinish: (to?: string) => Promise<void>;
}) {
  const t = useTranslations("setup");
  const [busy, setBusy] = useState(false);
  return (
    <section className="flex flex-col gap-6" aria-labelledby="setup-done-title">
      <header className="flex flex-col gap-1.5">
        <h1 id="setup-done-title" className="text-[22px] font-bold tracking-tight">
          {t("done.title")}
        </h1>
        <p className="text-sm text-muted-foreground">{t("done.description")}</p>
      </header>
      <ul className="flex flex-col divide-y rounded-lg border bg-card" data-testid="setup-summary">
        {SETUP_STEPS.map((step) => (
          <li key={step} className="flex items-center gap-3 px-4 py-3" data-step={step} data-set={steps[step]}>
            {steps[step] ? (
              <CheckIcon aria-hidden className="size-4 shrink-0 text-brand-soft-foreground" />
            ) : (
              <CircleDashedIcon aria-hidden className="size-4 shrink-0 text-muted-foreground" />
            )}
            <span className="flex-1 text-sm">
              {t(`steps.${step}.short`)}
              <span className="sr-only">, {steps[step] ? t("set") : t("notSet")}</span>
            </span>
            {!steps[step] && (
              <LeaveLink
                to={STEP_HOMES[step]}
                leave={(to) => void onFinish(to)}
                className="text-xs text-muted-foreground underline-offset-4 hover:underline"
              >
                {t("done.later")}
              </LeaveLink>
            )}
          </li>
        ))}
      </ul>
      <p className="text-sm text-muted-foreground">
        {t("done.advanced")}{" "}
        <LeaveLink to="/settings" leave={(to) => void onFinish(to)}>
          {t("done.settings")}
        </LeaveLink>
      </p>
      <div className="flex items-center gap-2 border-t pt-4">
        <Button type="button" variant="ghost" onClick={onBack}>
          <ArrowLeftIcon />
          {t("back")}
        </Button>
        <Button
          className="ml-auto"
          disabled={busy}
          data-testid="setup-finish"
          onClick={() => {
            setBusy(true);
            void onFinish().finally(() => setBusy(false));
          }}
        >
          {t("done.finish")}
          <ArrowRightIcon />
        </Button>
      </div>
    </section>
  );
}
