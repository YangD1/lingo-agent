"use client";

import { CheckCircle2, Circle } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { useState } from "react";

import { PlanEditor, roundMinutes, useItemLabel } from "@/components/plan/plan-editor";
import { Button, buttonVariants } from "@/components/ui/button";
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/empty-state";
import { ErrorText } from "@/components/ui/error-text";
import { type ApiErrorLike, useErrorMessage } from "@/i18n/errors";
import { ApiError } from "@/lib/api";
import { decideCard } from "@/lib/cards";
import {
  decidePlan,
  itemHref,
  type Plan,
  type PlanAction,
  type PlanChoice,
  type PlanItem,
} from "@/lib/plan";
import { cn } from "@/lib/utils";

/**
 * Today's plan (ADR 0027), above the tutor on the dashboard: drafted by code from the
 * learner's daily minutes, adjusted and confirmed here, then ticked off from what the
 * learner actually did. No model call: no AI badge.
 */
export function TodayPlan({
  plan,
  error,
  onChange,
  onReload,
}: {
  plan: Plan | null;
  error: string | null;
  onChange: (plan: Plan) => void;
  /** Read the plan again (after its tutor's card was undone). */
  onReload: () => void;
}) {
  const t = useTranslations("plan");
  return (
    <Card data-testid="today-plan" data-status={plan?.status}>
      <CardHeader>
        <CardTitle>{t("title")}</CardTitle>
        {plan && plan.status !== "declined" && (
          <CardDescription>
            {plan.budget_set
              ? t("budget", { n: plan.budget })
              : t.rich("budgetUnset", {
                  n: plan.budget,
                  link: (chunks) => (
                    <Link href="/memory" className="font-medium text-primary hover:underline">
                      {chunks}
                    </Link>
                  ),
                })}
          </CardDescription>
        )}
        {plan?.status === "applied" && plan.items.length > 0 && (
          <CardAction className="text-xs text-muted-foreground tabular-nums">
            {t("doneCount", {
              done: plan.items.filter((i) => i.complete).length,
              total: plan.items.length,
            })}
          </CardAction>
        )}
      </CardHeader>
      <CardContent>
        {!plan && !error && (
          <div role="status" aria-label={t("loading")}>
            <Skeleton className="h-24 rounded-lg" />
          </div>
        )}
        {!plan && error && <ErrorText>{error}</ErrorText>}
        {plan && (
          // A new plan from the server (the tutor's card, a reload) replaces local edits.
          <PlanBody
            key={`${plan.id}:${plan.status}:${JSON.stringify(plan.choice)}`}
            plan={plan}
            onChange={onChange}
            onReload={onReload}
          />
        )}
      </CardContent>
    </Card>
  );
}

function PlanBody({
  plan,
  onChange,
  onReload,
}: {
  plan: Plan;
  onChange: (plan: Plan) => void;
  onReload: () => void;
}) {
  const t = useTranslations("plan");
  const errorMessage = useErrorMessage();
  const [choice, setChoice] = useState<PlanChoice>(plan.choice);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiErrorLike | null>(null);

  const act = (action: PlanAction) => {
    setBusy(true);
    setError(null);
    // A plan from the tutor's card is undone on the card, which restores the one before.
    const request =
      action === "undo" && plan.card_id
        ? decideCard(plan.card_id, "undo").then(() => null)
        : decidePlan(plan.id, action, action === "confirm" ? choice : undefined);
    request.then(
      (updated) => {
        setBusy(false);
        if (updated) onChange(updated);
        else onReload();
      },
      (e: unknown) => {
        setBusy(false);
        setError(e instanceof ApiError ? e : { code: "network_error", message: String(e) });
      },
    );
  };

  const nothingOpen =
    plan.limits.reviews_due === 0 &&
    plan.limits.new_left === 0 &&
    !plan.limits.practice &&
    !plan.limits.reading;

  return (
    <div className="flex flex-col gap-3">
      {plan.status === "declined" && (
        <p className="text-[13px] text-muted-foreground" data-testid="plan-declined">
          {t("declined")}
        </p>
      )}
      {plan.status === "proposed" &&
        (nothingOpen && !choice.writing ? (
          <p className="text-[13px] text-muted-foreground">{t("nothing")}</p>
        ) : (
          <>
            <PlanEditor
              choice={choice}
              limits={plan.limits}
              estimates={plan.estimates}
              onChange={setChoice}
              disabled={busy}
            />
            <div className="flex flex-wrap items-center gap-2">
              <Button size="sm" disabled={busy} onClick={() => act("confirm")}>
                {t("confirm")}
              </Button>
              <Button size="sm" variant="ghost" disabled={busy} onClick={() => act("decline")}>
                {t("decline")}
              </Button>
              <span className="text-xs text-muted-foreground">{t("pending")}</span>
            </div>
          </>
        ))}
      {plan.status === "applied" && (
        <>
          {plan.items.length === 0 ? (
            <p className="text-[13px] text-muted-foreground">{t("emptyPlan")}</p>
          ) : (
            <ul className="flex flex-col divide-y rounded-lg border text-[13px]">
              {plan.items.map((item) => (
                <Checklist key={item.kind} item={item} />
              ))}
            </ul>
          )}
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs text-muted-foreground">
              {plan.items.length > 0 && plan.items.every((i) => i.complete)
                ? t("allDone")
                : t("total", { n: roundMinutes(plan.minutes) })}
              {plan.card_id && ` · ${t("fromTutor")}`}
            </span>
            <Button size="sm" variant="ghost" disabled={busy} onClick={() => act("undo")}>
              {t("undo")}
            </Button>
          </div>
        </>
      )}
      {error && <ErrorText size="xs">{errorMessage(error)}</ErrorText>}
    </div>
  );
}

function Checklist({ item }: { item: PlanItem }) {
  const t = useTranslations("plan");
  const label = useItemLabel();
  const Icon = item.complete ? CheckCircle2 : Circle;
  return (
    <li
      className="flex min-h-11 items-center gap-2.5 px-3 py-1.5"
      data-testid={`plan-item-${item.kind}`}
      data-complete={item.complete}
    >
      <Icon
        aria-hidden
        className={cn("size-4 shrink-0", item.complete ? "text-success" : "text-muted-foreground")}
      />
      <span className="min-w-0 flex-1">
        <span className={cn("block font-medium", item.complete && "text-muted-foreground")}>
          {label(item.kind, item.count, item.kc)}
          <span className="sr-only">{item.complete ? t("doneSr") : ""}</span>
        </span>
        {item.article && (
          <span className="block truncate text-xs text-muted-foreground">{item.article.title}</span>
        )}
      </span>
      {item.count !== null && (
        <span className="shrink-0 text-xs text-muted-foreground tabular-nums" data-testid="plan-progress">
          {t("progress", { done: Math.min(item.done, item.target), target: item.target })}
        </span>
      )}
      {!item.complete && (
        <Link href={itemHref(item)} className={buttonVariants({ size: "sm", variant: "outline" })}>
          {t(`go.${item.kind}`)}
        </Link>
      )}
    </li>
  );
}
