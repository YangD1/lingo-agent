"use client";

import { CheckIcon } from "lucide-react";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { useDescribeError } from "@/components/settings/use-describe-error";
import { ErrorText } from "@/components/ui/error-text";
import { api } from "@/lib/api";
import { HOME_PATH } from "@/lib/auth";
import {
  SETUP_STEPS,
  type SetupState,
  type SetupView,
  nextView,
  previousView,
  stepNumber,
} from "@/lib/setup";
import type { User } from "@/lib/types";
import { cn } from "@/lib/utils";

import { DoneStep } from "./done-step";
import { GoalsStep } from "./goals-step";
import { ModelStep } from "./model-step";
import { PlacementStep } from "./placement-step";
import { ProfileStep } from "./profile-step";
import type { StepNav } from "./step-frame";
import { TutorStep } from "./tutor-step";

/**
 * The setup guide (ADR 0042): five skippable steps, then a summary. Each step saves through
 * the pages' own endpoints; what is set up is read back from `/me/setup`, so a re-entered
 * guide shows ticks and current values.
 */
export function SetupApp({ user, initial }: { user: User; initial: SetupView }) {
  const t = useTranslations("setup");
  const router = useRouter();
  const describe = useDescribeError();
  const [view, setView] = useState<SetupView>(initial);
  const [state, setState] = useState<SetupState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const scroller = useRef<HTMLDivElement>(null);

  const refresh = () =>
    api<SetupState>("/me/setup").then(
      (next) => {
        setState(next);
        return next;
      },
      (e: unknown) => {
        setError(describe(e));
        return null;
      },
    );
  // eslint-disable-next-line react-hooks/exhaustive-deps -- load once
  useEffect(() => void refresh(), []);

  // Leaves the guide for `to`, marking it finished first (ADR 0042 §1).
  async function finish(to: string = HOME_PATH) {
    setError(null);
    try {
      await api<SetupState>("/me/setup/complete", { method: "POST" });
    } catch (e) {
      setError(describe(e));
      return;
    }
    router.replace(to);
    router.refresh();
  }

  const go = (to: SetupView) => {
    setError(null);
    setView(to);
    if (scroller.current) scroller.current.scrollTop = 0;
  };

  if (!state) {
    return error ? <ErrorText className="m-auto">{error}</ErrorText> : null;
  }

  const back = previousView(view);
  const nav: StepNav = {
    back: back ? () => go(back) : null,
    skip: () => go(nextView(view)),
    next: async () => {
      if (await refresh()) go(nextView(view));
    },
    skipAll: view === SETUP_STEPS[0] && !state.completed_at ? () => void finish() : null,
    leave: (to) => void finish(to),
  };

  return (
    <div ref={scroller} className="flex-1 overflow-y-auto" data-testid="setup">
      <div className="mx-auto flex max-w-xl flex-col gap-6 px-4 pt-2 pb-10 md:pt-8">
        <Stepper view={view} state={state} onPick={go} />
        {error && <ErrorText>{error}</ErrorText>}
        {view === "profile" && <ProfileStep user={user} nav={nav} />}
        {view === "model" && <ModelStep ready={state.steps.model} nav={nav} />}
        {view === "goals" && <GoalsStep nav={nav} />}
        {view === "tutor" && <TutorStep nav={nav} />}
        {view === "placement" && (
          <PlacementStep done={state.steps.placement} nav={nav} onStart={() => finish("/placement")} />
        )}
        {view === "done" && (
          <DoneStep
            steps={state.steps}
            onBack={() => go(SETUP_STEPS[SETUP_STEPS.length - 1])}
            onFinish={finish}
          />
        )}
        <p className="sr-only" aria-live="polite">
          {view === "done" ? t("done.title") : t("progress", { n: stepNumber(view), total: SETUP_STEPS.length })}
        </p>
      </div>
    </div>
  );
}

/** One dot per step, ticked when set up; any step can be jumped to. */
function Stepper({
  view,
  state,
  onPick,
}: {
  view: SetupView;
  state: SetupState;
  onPick: (view: SetupView) => void;
}) {
  const t = useTranslations("setup");
  return (
    <nav aria-label={t("stepsLabel")}>
      <ol className="flex items-start gap-1">
        {SETUP_STEPS.map((step, i) => {
          const current = step === view;
          const set = state.steps[step];
          return (
            <li key={step} className="flex flex-1 flex-col items-center gap-1.5">
              <button
                type="button"
                onClick={() => onPick(step)}
                aria-current={current ? "step" : undefined}
                data-testid={`setup-dot-${step}`}
                data-set={set || undefined}
                className={cn(
                  "flex size-7 items-center justify-center rounded-full border text-xs font-semibold tabular-nums outline-none transition-colors focus-visible:ring-3 focus-visible:ring-ring/50",
                  set ? "border-transparent bg-brand-soft text-brand-soft-foreground" : "bg-card text-muted-foreground",
                  current && "border-primary ring-2 ring-primary/30",
                )}
              >
                {set ? <CheckIcon aria-hidden className="size-3.5" /> : i + 1}
                <span className="sr-only">
                  {t(`steps.${step}.short`)}
                  {set && `, ${t("set")}`}
                </span>
              </button>
              <span
                aria-hidden
                className={cn(
                  "text-center text-[11px] leading-tight text-muted-foreground max-sm:hidden",
                  current && "font-medium text-foreground",
                )}
              >
                {t(`steps.${step}.short`)}
              </span>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
