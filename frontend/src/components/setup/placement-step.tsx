"use client";

import { CheckCircle2Icon, TimerIcon } from "lucide-react";
import { useTranslations } from "next-intl";

import { Callout } from "@/components/ui/callout";

import { type StepNav, StepFrame } from "./step-frame";

/**
 * Step 5: the placement test now or later (ADR 0042 §2). Starting it finishes the guide
 * first, so the test page opens inside the app.
 */
export function PlacementStep({
  done,
  nav,
  onStart,
}: {
  done: boolean;
  nav: StepNav;
  onStart: () => void;
}) {
  const t = useTranslations("setup.steps.placement");
  if (done) {
    return (
      <StepFrame step="placement" nav={nav} onSubmit={() => void nav.next()}>
        <Callout tone="brand" icon={<CheckCircle2Icon aria-hidden />}>
          <span className="flex-1">{t("taken")}</span>
        </Callout>
      </StepFrame>
    );
  }
  return (
    <StepFrame step="placement" nav={nav} onSubmit={onStart} submitLabel={t("start")}>
      <Callout icon={<TimerIcon aria-hidden />}>
        <span className="flex-1">{t("what")}</span>
      </Callout>
    </StepFrame>
  );
}
