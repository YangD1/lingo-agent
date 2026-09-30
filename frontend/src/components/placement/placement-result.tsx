"use client";

import Link from "next/link";
import { useFormatter, useTranslations } from "next-intl";
import { useState } from "react";

import { AiBadge } from "@/components/ai-badge";
import { AdviceEntry, AdviceStatus, useAdvice } from "@/components/dashboard/advice-card";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { PlacementKnown } from "@/components/vocab/placement-known";
import { PLAN_HREF, type PlacementResult as Result } from "@/lib/placement";

/**
 * The finished test: the overall level (the grammar level, Q15d), the vocabulary size
 * with its rough reference level, what to do next (the advice, rewritten for the new
 * result, and a planning conversation with the tutor), the offer to mark common words
 * known, and a retest.
 */
export function PlacementResult({
  result,
  finishedAt,
  busy,
  onRetest,
}: {
  result: Result;
  finishedAt: string | null;
  busy: boolean;
  onRetest: () => void;
}) {
  const t = useTranslations("placement.result");
  const format = useFormatter();
  const [confirming, setConfirming] = useState(false);
  const { vocab, grammar } = result;

  return (
    <>
      <Card data-testid="placement-result">
        <CardHeader>
          <CardTitle>{t("title")}</CardTitle>
          {finishedAt && (
            <CardDescription>
              {t("finishedAt", { date: format.dateTime(new Date(finishedAt), { dateStyle: "medium" }) })}
            </CardDescription>
          )}
        </CardHeader>
        <CardContent className="flex flex-col gap-4 text-sm">
          <div>
            <p className="text-4xl font-semibold" data-testid="placement-level">
              {result.cefr}
            </p>
            <p className="text-muted-foreground">{t("levelNote")}</p>
          </div>
          <dl className="grid gap-3 sm:grid-cols-2">
            <div className="rounded-lg border p-3">
              <dt className="text-muted-foreground">{t("grammar")}</dt>
              <dd className="text-lg font-medium">{grammar.cefr}</dd>
              <dd className="text-xs text-muted-foreground">
                {t("grammarNote", { answered: grammar.answered })}
              </dd>
            </div>
            <div className="rounded-lg border p-3">
              <dt className="text-muted-foreground">{t("vocab")}</dt>
              <dd className="text-lg font-medium" data-testid="placement-vocab-size">
                {t("vocabSize", { size: format.number(vocab.size) })}
              </dd>
              <dd className="text-xs text-muted-foreground">
                {vocab.reference_cefr
                  ? t("vocabReference", { level: vocab.reference_cefr })
                  : t("vocabNote")}
              </dd>
            </div>
          </dl>
          {!vocab.reliable && (
            <p className="text-amber-700 dark:text-amber-400" data-testid="placement-unreliable">
              {t("unreliable")}
            </p>
          )}
        </CardContent>
      </Card>

      <NextSteps />

      <Card>
        <CardHeader>
          <CardTitle>{t("knownTitle")}</CardTitle>
          <CardDescription>{t("knownDescription")}</CardDescription>
        </CardHeader>
        <CardContent>
          <PlacementKnown />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t("retestTitle")}</CardTitle>
          <CardDescription>{t("retestDescription")}</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap gap-2">
          {confirming ? (
            <>
              <Button size="sm" variant="destructive" disabled={busy} onClick={onRetest}>
                {t("retestConfirm")}
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setConfirming(false)}>
                {t("cancel")}
              </Button>
            </>
          ) : (
            <Button size="sm" variant="outline" onClick={() => setConfirming(true)}>
              {t("retest")}
            </Button>
          )}
        </CardContent>
      </Card>
    </>
  );
}

/** The top advice for the new result, and the way into a planning conversation. */
function NextSteps() {
  const t = useTranslations("placement.result");
  const { advice, error } = useAdvice();
  return (
    <Card data-testid="placement-next">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          {t("nextTitle")}
          <AiBadge feature="advice" />
        </CardTitle>
        <CardDescription>{advice ? <AdviceStatus advice={advice} /> : t("nextLoading")}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}
        {advice && advice.items.length > 0 && (
          <ol className="grid gap-3 md:grid-cols-3">
            {advice.items.map((item) => (
              <AdviceEntry key={item.candidate_id} item={item} />
            ))}
          </ol>
        )}
        <div className="flex flex-col gap-2">
          <p className="text-sm text-muted-foreground">{t("planNote")}</p>
          <div className="flex flex-wrap items-center gap-2">
            <Link href={PLAN_HREF} className={buttonVariants()} data-testid="placement-plan">
              {t("plan")}
            </Link>
            <AiBadge feature="plan_start" />
            <Link href="/vocab" className={buttonVariants({ variant: "outline" })}>
              {t("toVocab")}
            </Link>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
