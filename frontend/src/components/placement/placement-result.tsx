"use client";

import { TriangleAlert } from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Callout } from "@/components/ui/callout";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { CefrTag, isCefrLevel } from "@/components/ui/tag";
import { PlacementKnown } from "@/components/vocab/placement-known";
import type { PlacementResult as Result } from "@/lib/placement";

import { PlacementTutor } from "./placement-tutor";

/**
 * The finished test: the overall level (the grammar level, Q15d), the vocabulary size
 * with its rough reference level, what to do next (the planning conversation with the
 * tutor, in the page), the offer to mark common words known, and a retest.
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
          <CardTitle>
            <h1>{t("title")}</h1>
          </CardTitle>
          {finishedAt && (
            <CardDescription>
              {t("finishedAt", { date: format.dateTime(new Date(finishedAt), { dateStyle: "medium" }) })}
            </CardDescription>
          )}
        </CardHeader>
        <CardContent className="flex flex-col gap-4 text-sm">
          <div className="grid gap-3 sm:grid-cols-[minmax(7rem,auto)_1fr_1fr]">
            <div className="flex flex-col items-center justify-center gap-1.5 py-2">
              <p
                className="font-mono text-5xl leading-none font-bold tracking-tight"
                data-testid="placement-level"
              >
                {result.cefr}
              </p>
              {isCefrLevel(result.cefr) && <CefrTag level={result.cefr} />}
            </div>
            <dl className="contents">
              <div className="flex flex-col gap-0.5 rounded-lg border bg-muted/50 p-4">
                <dt className="text-xs text-muted-foreground">{t("grammar")}</dt>
                <dd className="font-mono text-lg font-bold">{grammar.cefr}</dd>
                <dd className="text-xs text-muted-foreground">
                  {t("grammarNote", { answered: grammar.answered })}
                </dd>
              </div>
              <div className="flex flex-col gap-0.5 rounded-lg border bg-muted/50 p-4">
                <dt className="text-xs text-muted-foreground">{t("vocab")}</dt>
                <dd className="text-lg font-bold" data-testid="placement-vocab-size">
                  {t("vocabSize", { size: format.number(vocab.size) })}
                </dd>
                <dd className="text-xs text-muted-foreground">
                  {vocab.reference_cefr
                    ? t("vocabReference", { level: vocab.reference_cefr })
                    : t("vocabNote")}
                </dd>
              </div>
            </dl>
          </div>
          <p className="text-[13px] text-muted-foreground">{t("levelNote")}</p>
          {!vocab.reliable && (
            <Callout tone="warning" icon={<TriangleAlert />} data-testid="placement-unreliable">
              {t("unreliable")}
            </Callout>
          )}
        </CardContent>
      </Card>

      <PlacementTutor finishedAt={finishedAt} />

      <Card>
        <CardHeader>
          <CardTitle>{t("knownTitle")}</CardTitle>
          <CardDescription>{t("knownDescription")}</CardDescription>
        </CardHeader>
        <CardContent>
          <PlacementKnown bare />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t("retestTitle")}</CardTitle>
          <CardDescription>{t("retestDescription")}</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap items-center gap-2">
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
