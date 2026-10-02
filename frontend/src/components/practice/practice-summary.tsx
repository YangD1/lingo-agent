"use client";

import { ArrowRight, GraduationCap } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import Link from "next/link";

import { AiBadge } from "@/components/ai-badge";
import { LingoCat } from "@/components/brand/lingo-cat";
import { STATE_BAR } from "@/components/learner/kc-item";
import { PlacementReminder } from "@/components/placement/placement-reminder";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ProgressBar } from "@/components/ui/progress";
import { CefrTag, Tag } from "@/components/ui/tag";
import { kcName, learnerHref } from "@/lib/learner";
import type { HowMade, KCChange, PracticeSet } from "@/lib/practice";

/** A finished set (P2 plan §3.7): the done cat, the score, each grammar point's mastery
 * before and after, how the items were made, and another set. */
export function PracticeSummary({
  set,
  busy,
  onAgain,
}: {
  set: PracticeSet;
  busy: boolean;
  onAgain: () => void;
}) {
  const t = useTranslations("practice.summary");
  const summary = set.summary!;
  return (
    <Card data-testid="practice-summary">
      <CardHeader>
        <CardTitle className="flex items-center gap-2.5">
          {/* Plays on every finish; reduced motion shows the still logo. */}
          <LingoCat mood="done" size={40} label="" />
          <h1>{t("title")}</h1>
        </CardTitle>
        <CardDescription data-testid="practice-score">
          {t("score", { correct: summary.correct, total: summary.total })}
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-5 text-sm">
        <ul className="flex flex-col divide-y" aria-label={t("kcs")}>
          {summary.kcs.map((change) => (
            <KCRow key={change.kc.id} change={change} />
          ))}
        </ul>
        {set.how_made && <MadeBy how={set.how_made} />}
        {/* Enough of the level learned, or the last test getting old (Q50b). */}
        <PlacementReminder reasons={["progress", "age"]} />
        <div className="flex flex-wrap items-center gap-2">
          <Button disabled={busy} onClick={onAgain} data-testid="practice-again">
            {t("again")}
          </Button>
          <AiBadge feature="practice_set" />
          <Link href="/learner" className={buttonVariants({ variant: "outline" })}>
            {t("toLearner")}
          </Link>
        </div>
      </CardContent>
    </Card>
  );
}

function percent(p: number | null) {
  return p === null ? null : Math.round(p * 100);
}

function KCRow({ change }: { change: KCChange }) {
  const t = useTranslations("practice.summary");
  const locale = useLocale();
  const before = percent(change.before.p_mastery);
  const after = percent(change.after.p_mastery);
  const newlyLearned = change.after.learned && !change.before.learned;
  return (
    <li className="flex flex-col gap-1.5 py-3" data-testid={`practice-kc-${change.kc.id}`}>
      <div className="flex flex-wrap items-center gap-2">
        <Link href={learnerHref(change.kc.id)} className="font-[550] hover:underline">
          {kcName(change.kc, locale)}
        </Link>
        {change.kc.cefr && <CefrTag level={change.kc.cefr} />}
        {newlyLearned && (
          <Tag variant="success">
            <GraduationCap aria-hidden />
            {t("newlyLearned")}
          </Tag>
        )}
        <span className="ml-auto text-xs text-muted-foreground tabular-nums">
          {change.items > 0 ? t("answered", { correct: change.correct, total: change.items }) : t("notCounted")}
        </span>
      </div>
      {after !== null && change.after.state && (
        <div className="flex items-center gap-3">
          <ProgressBar
            value={change.after.p_mastery ?? 0}
            barClassName={STATE_BAR[change.after.state]}
            className="flex-1"
          />
          <span className="flex shrink-0 items-center gap-1 text-xs text-muted-foreground tabular-nums">
            {before === null ? (
              t("firstTime", { after })
            ) : (
              <>
                {before}%
                <ArrowRight aria-label={t("to")} className="size-3" />
                {after}%
              </>
            )}
          </span>
        </div>
      )}
    </li>
  );
}

function MadeBy({ how }: { how: HowMade }) {
  const t = useTranslations("practice.summary.madeBy");
  const parts = [
    how.written > 0 &&
      t("written", {
        n: how.written,
        writers: how.writers.join(", ") || "—",
        reviewers: how.reviewers.join(", ") || "—",
      }),
    how.from_bank > 0 && t("fromBank", { n: how.from_bank }),
    how.rejected > 0 && t("rejected", { n: how.rejected }),
  ].filter(Boolean);
  return (
    <p className="text-xs text-muted-foreground" data-testid="practice-made-by">
      {parts.join(t("separator"))}
    </p>
  );
}
