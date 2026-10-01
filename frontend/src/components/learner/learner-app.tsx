"use client";

import Link from "next/link";
import { useFormatter, useTranslations } from "next-intl";
import { useCallback, useEffect, useState } from "react";

import { useDescribeError } from "@/components/settings/use-describe-error";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { NativeSelect } from "@/components/ui/native-select";
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

import { KCItem } from "./kc-item";

/**
 * The learner model (ADR 0010): grammar mastery computed from evidence, with the evidence
 * itself, skill estimates, and deleting all of it. `focusKc` opens one grammar point.
 */
export function LearnerApp({ focusKc }: { focusKc: string | null }) {
  const t = useTranslations("learner");
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
  // Ratings are on different scales (vocab stores ln V), so show what each one means.
  const skillRow = (s: SkillEstimate) => {
    const skill = skillName(s.skill);
    if (s.vocab_size !== null) {
      const size = format.number(s.vocab_size);
      const row = s.cefr
        ? t("skills.vocabRowLevel", { skill, size, level: s.cefr })
        : t("skills.vocabRow", { skill, size });
      return s.reliable === false ? `${row} ${t("skills.unreliable")}` : row;
    }
    if (s.cefr) return t("skills.levelRow", { skill, level: s.cefr, attempts: s.attempts });
    return t("skills.row", { skill, rating: s.rating.toFixed(2), attempts: s.attempts });
  };
  const shown = model ? filterKcs(model.kcs, filter) : [];

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="mx-auto flex max-w-3xl flex-col gap-6 p-4 md:p-8">
        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
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
              <p className="text-sm text-muted-foreground">{t("grammar.empty")}</p>
            )}
            {model && model.kcs.length > 0 && (
              <>
                <p className="text-xs text-muted-foreground" data-testid="level-coverage">
                  {CEFR_LEVELS.filter((l) => model.levels[l])
                    .map((l) => t("grammar.coverage", { level: l, ...model.levels[l]! }))
                    .join(" · ")}
                </p>
                <div className="flex flex-wrap gap-2">
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
                </div>
                {shown.length === 0 ? (
                  <p className="text-sm text-muted-foreground">{t("grammar.noMatch")}</p>
                ) : (
                  <ul className="flex flex-col divide-y" aria-label={t("grammar.title")}>
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
              <p className="text-sm text-muted-foreground">
                {t("skills.empty")}{" "}
                <Link href="/placement" className="underline underline-offset-2">
                  {t("skills.takeTest")}
                </Link>
              </p>
            )}
            {model && model.skills.length > 0 && (
              <ul className="flex flex-col gap-1 text-sm">
                {model.skills.map((s) => (
                  <li key={s.skill} data-testid={`skill-${s.skill}`}>
                    {skillRow(s)}
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>{t("clear.title")}</CardTitle>
            <CardDescription>{t("clear.description")}</CardDescription>
          </CardHeader>
          <CardContent>
            <ConfirmDialog
              trigger={
                <Button variant="destructive" size="sm" disabled={busy}>
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
