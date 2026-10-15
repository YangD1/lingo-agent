"use client";

import { ArrowLeftIcon } from "lucide-react";
import { useTranslations } from "next-intl";
import type { FormEvent, ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { ErrorText } from "@/components/ui/error-text";
import { SETUP_STEPS, type SetupStep, stepNumber } from "@/lib/setup";

/** What a step can do besides saving: provided by the guide. */
export type StepNav = {
  back: (() => void) | null;
  skip: () => void;
  /** After saving: re-reads where setup stands, then moves on. */
  next: () => Promise<void>;
  /** "Skip all" on the first step of a guide not yet finished (ADR 0042 §1). */
  skipAll: (() => void) | null;
  /** Leaves the guide for another page, finishing it first: unfinished, the app would send the learner back. */
  leave: (to: string) => void;
};

/** A link out of the guide, e.g. to the settings page for what the guide leaves out. */
export function LeaveLink({
  to,
  leave,
  className,
  children,
}: {
  to: string;
  leave: (to: string) => void;
  className?: string;
  children: ReactNode;
}) {
  return (
    <a
      href={to}
      onClick={(e) => {
        e.preventDefault();
        leave(to);
      }}
      className={className ?? "font-medium underline-offset-4 hover:underline"}
    >
      {children}
    </a>
  );
}

/**
 * A step's title, body and buttons. The body is a form: Enter or the main button submits it;
 * the step saves and calls `nav.next()`. `extra` sits below it, outside the form, for
 * controls with forms of their own.
 */
export function StepFrame({
  step,
  nav,
  onSubmit,
  submitLabel,
  busy = false,
  error,
  skipConfirm,
  extra,
  children,
}: {
  step: SetupStep;
  nav: StepNav;
  onSubmit: () => void;
  submitLabel?: string;
  busy?: boolean;
  error?: string | null;
  /** Asks before skipping, for a step the app can hardly do without (Q82e). */
  skipConfirm?: { title: string; description: string; confirmLabel: string; cancelLabel: string };
  extra?: ReactNode;
  children?: ReactNode;
}) {
  const t = useTranslations("setup");
  const skip = (
    <Button type="button" variant="ghost" data-testid="setup-skip" onClick={skipConfirm ? undefined : nav.skip}>
      {t("skip")}
    </Button>
  );
  const formId = `setup-${step}-form`;
  return (
    <section className="flex flex-col gap-6" aria-labelledby={`setup-${step}-title`}>
      <header className="flex flex-col gap-1.5">
        <p className="text-xs font-medium text-muted-foreground">
          {t("progress", { n: stepNumber(step), total: SETUP_STEPS.length })}
        </p>
        <h1 id={`setup-${step}-title`} className="text-[22px] font-bold tracking-tight">
          {t(`steps.${step}.title`)}
        </h1>
        <p className="text-sm text-muted-foreground">{t(`steps.${step}.description`)}</p>
      </header>
      <form
        id={formId}
        className="flex flex-col gap-5 empty:hidden"
        onSubmit={(e: FormEvent) => {
          e.preventDefault();
          if (!busy) onSubmit();
        }}
      >
        {children}
      </form>
      {extra}
      {error && <ErrorText>{error}</ErrorText>}
      <div className="flex flex-wrap items-center gap-2 border-t pt-4">
        {nav.back && (
          <Button type="button" variant="ghost" onClick={nav.back}>
            <ArrowLeftIcon />
            {t("back")}
          </Button>
        )}
        {nav.skipAll && (
          <Button type="button" variant="link" className="text-muted-foreground" onClick={nav.skipAll} data-testid="setup-skip-all">
            {t("skipAll")}
          </Button>
        )}
        <div className="ml-auto flex items-center gap-2">
          {skipConfirm ? (
            <ConfirmDialog
              trigger={skip}
              title={skipConfirm.title}
              description={skipConfirm.description}
              confirmLabel={skipConfirm.confirmLabel}
              cancelLabel={skipConfirm.cancelLabel}
              tone="default"
              onConfirm={nav.skip}
            />
          ) : (
            skip
          )}
          <Button type="submit" form={formId} disabled={busy} data-testid="setup-next">
            {submitLabel ?? t("next")}
          </Button>
        </div>
      </div>
    </section>
  );
}
