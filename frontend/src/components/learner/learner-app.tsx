"use client";

import { MessageCircle, Trash2 } from "lucide-react";
import Link from "next/link";
import { useFormatter, useTranslations } from "next-intl";
import { useCallback, useEffect, useState } from "react";

import { ChartLegend } from "@/components/dashboard/chart-legend";
import { useDescribeError } from "@/components/settings/use-describe-error";
import { Button, buttonVariants } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { NativeSelect } from "@/components/ui/native-select";
import { ProgressBar } from "@/components/ui/progress";
import { CefrTag } from "@/components/ui/tag";
import { ErrorText } from "@/components/ui/error-text";
import {
  CEFR_LEVELS,
  deleteLearner,
  fetchLearner,
  filterKcs,
  type KCFilter,
  type LearnerModel,
  MASTERY_STATES,
  type SkillEstimate,
} from "@/lib/learner";

import { KCItem, STATE_BAR } from "./kc-item";

const SKILLS = ["grammar", "vocab", "reading", "listening", "speaking", "writing"] as const;
const emptyButton = buttonVariants({ size: "sm", variant: "outline" });

/**
 * The learner model (ADR 0010): grammar mastery computed from evidence, with the evidence
 * itself, skill estimates, and deleting all of it. `focusKc` opens one grammar point.
 */
export function LearnerApp({ focusKc }: { focusKc: string | null }) {
  const t = useTranslations("learner");
  const tNav = useTranslations("nav");
  const format = useFormatter();
  const describe = useDescribeError();
  const [model, setModel] = useState<LearnerModel | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [filter, setFilter] = useState<KCFilter>({ level: "all", state: "all" });

  const load = useCallback(
    () => fetchLearner().then(setModel, (e: unknown) => setError(describe(e))),
    // eslint-disable-next-line react-hooks/exhaustive-deps -- describe is stable enough
    [],
  );

  useEffect(() => {
    void load();
  }, [load]);

  async function clear() {
    setBusy(true);
    setError(null);
    try {
      await deleteLearner();
      await load();
    } catch (e) {
      setError(describe(e));
    } finally {
      setBusy(false);
    }
  }

  const skillName = (skill: string) => {
    const key = `skills.names.${skill}` as Parameters<typeof t>[0];
    return t.has(key) ? t(key) : skill;
  };
  // Ratings are on different scales (vocab stores ln V), so say what each one is based on.
  const skillDetail = (s: SkillEstimate) => {
    if (s.vocab_size !== null) {
      const size = t("skills.vocab", { size: format.number(s.vocab_size) });
      return s.reliable === false ? `${size} ${t("skills.unreliable")}` : size;
    }
    if (s.cefr) return t("skills.answers", { attempts: s.attempts });
    return t("skills.rating", { rating: s.rating.toFixed(2), attempts: s.attempts });
  };
  const shown = model ? filterKcs(model.kcs, filter) : [];

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="mx-auto flex max-w-5xl flex-col gap-3.5 p-4 md:gap-4 md:px-10 md:py-8">
        <h1 className="mb-1 text-[26px] font-bold tracking-tight max-md:sr-only">
          {tNav("learner")}
        </h1>
        {error && (
          <ErrorText>{error}</ErrorText>
        )}
        <Card data-testid="learner-grammar">
          <CardHeader>
            <CardTitle>{t("grammar.title")}</CardTitle>
            <CardDescription>
              {model &&
                t("grammar.description", {
                  mastered: Math.round(model.thresholds.mastered * 100),
                  weak: Math.round(model.thresholds.weak * 100),
                })}
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            {model && model.kcs.length === 0 && (
              <EmptyState
                title={t("grammar.emptyTitle")}
                description={t("grammar.empty")}
                action={
                  <Link href="/chat" className={emptyButton}>
                    <MessageCircle />
                    {t("grammar.chat")}
                  </Link>
                }
              />
            )}
            {model && model.kcs.length > 0 && (
              <>
                <p
                  className="font-mono text-[11.5px] text-muted-foreground"
                  data-testid="level-coverage"
                >
                  {CEFR_LEVELS.filter((l) => model.levels[l])
                    .map((l) => t("grammar.coverage", { level: l, ...model.levels[l]! }))
                    .join(" · ")}
                </p>
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-xs text-muted-foreground">{t("grammar.filter")}</span>
                  <NativeSelect
                    aria-label={t("grammar.filterLevel")}
                    value={filter.level}
                    onChange={(e) =>
                      setFilter({ ...filter, level: e.target.value as KCFilter["level"] })
                    }
                  >
                    <option value="all">{t("grammar.allLevels")}</option>
                    {CEFR_LEVELS.map((l) => (
                      <option key={l} value={l}>
                        {l}
                      </option>
                    ))}
                  </NativeSelect>
                  <NativeSelect
                    aria-label={t("grammar.filterState")}
                    value={filter.state}
                    onChange={(e) =>
                      setFilter({ ...filter, state: e.target.value as KCFilter["state"] })
                    }
                  >
                    <option value="all">{t("grammar.allStates")}</option>
                    {MASTERY_STATES.map((s) => (
                      <option key={s} value={s}>
                        {t(`kc.states.${s}`)}
                      </option>
                    ))}
                  </NativeSelect>
                  <ChartLegend
                    className="ml-auto"
                    items={MASTERY_STATES.map((state) => ({
                      key: state,
                      label: t(`kc.states.${state}`),
                      swatch: STATE_BAR[state],
                    }))}
                  />
                </div>
                {shown.length === 0 ? (
                  <p className="text-sm text-muted-foreground">{t("grammar.noMatch")}</p>
                ) : (
                  <ul className="flex flex-col divide-y border-b" aria-label={t("grammar.title")}>
                    {shown.map((kc) => (
                      <KCItem
                        key={kc.kc_id}
                        kc={kc}
                        initiallyOpen={kc.kc_id === focusKc}
                        onChanged={() => void load()}
                      />
                    ))}
                  </ul>
                )}
              </>
            )}
          </CardContent>
        </Card>

        <Card data-testid="learner-skills">
          <CardHeader>
            <CardTitle>{t("skills.title")}</CardTitle>
            <CardDescription>{t("skills.description")}</CardDescription>
          </CardHeader>
          <CardContent>
            {model && model.skills.length === 0 && (
              <EmptyState
                title={t("skills.empty")}
                description={t("skills.emptyHint")}
                action={
                  <Link href="/placement" className={emptyButton}>
                    {t("skills.takeTest")}
                  </Link>
                }
              />
            )}
            {model && model.skills.length > 0 && (
              <ul className="flex flex-col divide-y text-[13px]">
                {SKILLS.map((skill) => {
                  const s = model.skills.find((e) => e.skill === skill);
                  const level = s?.cefr ? CEFR_LEVELS.indexOf(s.cefr) + 1 : 0;
                  return (
                    <li
                      key={skill}
                      data-testid={`skill-${skill}`}
                      className="flex min-h-11 items-center gap-3 py-2"
                    >
                      <span className="w-12 shrink-0">{skillName(skill)}</span>
                      {s ? (
                        <>
                          {s.cefr ? (
                            <ProgressBar value={level / 6} barClassName="bg-chart-1" />
                          ) : (
                            <span className="flex-1" />
                          )}
                          {s.cefr && <CefrTag level={s.cefr} className="shrink-0" />}
                          <span className="shrink-0 text-right text-xs text-muted-foreground">
                            {skillDetail(s)}
                          </span>
                        </>
                      ) : (
                        <>
                          <span className="flex-1 text-muted-foreground">
                            {t("skills.notAssessed")}
                          </span>
                          <Link href="/placement" className="text-xs font-medium text-primary hover:underline">
                            {t("skills.takeTest")}
                          </Link>
                        </>
                      )}
                    </li>
                  );
                })}
              </ul>
            )}
          </CardContent>
        </Card>

        <Card className="border-destructive/35">
          <CardHeader>
            <CardTitle>{t("clear.title")}</CardTitle>
            <CardDescription>{t("clear.description")}</CardDescription>
          </CardHeader>
          <CardContent>
            <ConfirmDialog
              trigger={
                <Button variant="destructive" size="sm" disabled={busy}>
                  <Trash2 />
                  {t("clear.button")}
                </Button>
              }
              title={t("clear.title")}
              description={t("clear.confirm")}
              onConfirm={() => void clear()}
            />
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
