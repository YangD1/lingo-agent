"use client";

import Link from "next/link";
import { useFormatter, useLocale, useTranslations } from "next-intl";
import { type ReactNode, useEffect, useState } from "react";

import { AiBadge } from "@/components/ai-badge";
import { useDescribeError } from "@/components/settings/use-describe-error";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  type Dashboard,
  fetchDashboard,
  hasActivity,
  hasGrammar,
  type SkillPoint,
} from "@/lib/dashboard";
import { CEFR_LEVELS, kcName, learnerHref, practiceHref } from "@/lib/learner";

import { ActivityHeatmap } from "./activity-heatmap";
import { BookChart } from "./book-chart";
import { ErrorsChart } from "./errors-chart";
import { GrammarChart } from "./grammar-chart";
import { SkillsChart } from "./skills-chart";
import { TodayTutor } from "./today-tutor";

/** Skills the dashboard always lists; P1 only measures grammar and vocabulary. */
const SKILLS = ["grammar", "vocab", "listening", "speaking", "reading", "writing"] as const;

const linkClass = "underline underline-offset-2";

/**
 * The ability dashboard (P1 plan §7.5): where the learner stands, as numbers and charts,
 * all from one aggregate. Every section without data says how to get some.
 */
export function DashboardApp() {
  const t = useTranslations("dashboard");
  const describe = useDescribeError();
  const [board, setBoard] = useState<Dashboard | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = () => fetchDashboard().then(setBoard, (e: unknown) => setError(describe(e)));
  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- describe is stable enough
  }, []);

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="mx-auto flex max-w-5xl flex-col gap-6 p-4 md:p-8">
        <h1 className="text-2xl font-semibold">{t("title")}</h1>
        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}
        {!board && !error && <p className="text-sm text-muted-foreground">{t("loading")}</p>}
        {board && (
          <>
            <SummaryCards board={board} />
            {/* A turn counts toward today's numbers and the streak. */}
            <TodayTutor onTurnFinished={() => void load()} />
            <div className="grid gap-6 md:grid-cols-2">
              <BookSection board={board} />
              <SkillsSection board={board} />
              <GrammarSection board={board} />
              <ErrorsSection board={board} />
            </div>
            <ActivitySection board={board} />
          </>
        )}
      </div>
    </div>
  );
}

function Section({
  title,
  description,
  testId,
  children,
}: {
  title: string;
  description?: string;
  testId: string;
  children: ReactNode;
}) {
  return (
    <Card data-testid={testId}>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        {description && <CardDescription>{description}</CardDescription>}
      </CardHeader>
      <CardContent className="flex flex-col gap-4">{children}</CardContent>
    </Card>
  );
}

function Empty({ children }: { children: ReactNode }) {
  return <p className="text-sm text-muted-foreground">{children}</p>;
}

function Stat({
  label,
  value,
  note,
  testId,
}: {
  label: string;
  value: ReactNode;
  note?: ReactNode;
  testId: string;
}) {
  return (
    <Card size="sm" data-testid={testId}>
      <CardContent className="flex flex-col gap-1">
        <span className="text-sm text-muted-foreground">{label}</span>
        <span className="text-2xl font-semibold">{value}</span>
        {note && <span className="text-xs text-muted-foreground">{note}</span>}
      </CardContent>
    </Card>
  );
}

function SummaryCards({ board }: { board: Dashboard }) {
  const t = useTranslations("dashboard.summary");
  const format = useFormatter();
  const s = board.summary;
  const test = (
    <Link href="/placement" className={linkClass}>
      {t("takeTest")}
    </Link>
  );
  return (
    <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
      <Stat
        testId="stat-level"
        label={t("level")}
        value={s.cefr ?? t("none")}
        note={s.cefr ? t("levelNote") : test}
      />
      <Stat
        testId="stat-vocab"
        label={t("vocab")}
        value={s.vocab_size === null ? t("none") : t("words", { n: format.number(s.vocab_size) })}
        note={
          s.vocab_size === null
            ? test
            : [
                s.vocab_cefr && t("vocabLevel", { level: s.vocab_cefr }),
                s.vocab_reliable === false && t("unreliable"),
              ]
                .filter(Boolean)
                .join(" ")
        }
      />
      <Stat
        testId="stat-streak"
        label={t("streak")}
        value={t("days", { n: s.streak_days })}
        note={
          s.studied_today ? t("studiedToday") : s.streak_days > 0 ? t("keepGoing") : t("start")
        }
      />
      <Stat
        testId="stat-today"
        label={t("today")}
        value={t("reviews", { n: s.reviews_due })}
        note={
          s.reviews_due + s.new_left > 0 ? (
            <Link href="/vocab/review" className={linkClass}>
              {t("newLeft", { n: s.new_left })}
            </Link>
          ) : (
            t("allDone")
          )
        }
      />
    </div>
  );
}

function BookSection({ board }: { board: Dashboard }) {
  const t = useTranslations("dashboard.book");
  const locale = useLocale();
  const book = board.book;
  return (
    <Section
      testId="dashboard-book"
      title={t("title")}
      description={book ? (locale.startsWith("zh") ? book.name_zh : book.name_en) : undefined}
    >
      {book ? (
        <>
          <BookChart book={book} />
          <p className="text-sm" data-testid="book-summary">
            {t("summary", { ...book })}
          </p>
        </>
      ) : (
        <Empty>
          {t("empty")}{" "}
          <Link href="/vocab" className={linkClass}>
            {t("choose")}
          </Link>
        </Empty>
      )}
    </Section>
  );
}

function GrammarSection({ board }: { board: Dashboard }) {
  const t = useTranslations("dashboard.grammar");
  return (
    <Section testId="dashboard-grammar" title={t("title")} description={t("description")}>
      {hasGrammar(board.grammar) ? (
        <>
          <GrammarChart grammar={board.grammar} />
          <table className="w-full text-sm" data-testid="grammar-table">
            <caption className="sr-only">{t("title")}</caption>
            <thead className="text-muted-foreground">
              <tr>
                <th scope="col" className="text-left font-normal">{t("level")}</th>
                <th scope="col" className="text-right font-normal">{t("mastered")}</th>
                <th scope="col" className="text-right font-normal">{t("learning")}</th>
                <th scope="col" className="text-right font-normal">{t("weak")}</th>
                <th scope="col" className="text-right font-normal">{t("unseen")}</th>
              </tr>
            </thead>
            <tbody className="tabular-nums">
              {CEFR_LEVELS.map((level) => {
                const l = board.grammar[level];
                return (
                  <tr key={level}>
                    <th scope="row" className="text-left font-normal">{level}</th>
                    <td className="text-right">{l.mastered}</td>
                    <td className="text-right">{l.learning}</td>
                    <td className="text-right">{l.weak}</td>
                    <td className="text-right">{l.unseen}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </>
      ) : (
        <Empty>
          {t.rich("empty", {
            chat: (text) => (
              <Link href="/chat" className={linkClass}>
                {text}
              </Link>
            ),
            test: (text) => (
              <Link href="/placement" className={linkClass}>
                {text}
              </Link>
            ),
          })}
        </Empty>
      )}
    </Section>
  );
}

function SkillsSection({ board }: { board: Dashboard }) {
  const t = useTranslations("dashboard.skills");
  const tl = useTranslations("learner.skills.names");
  const format = useFormatter();
  const measured = new Map(board.skills.map((s) => [s.skill, s]));
  const name = (skill: string) => (tl.has(skill as never) ? tl(skill as never) : skill);
  const value = (s: SkillPoint) => {
    if (s.vocab_size !== null)
      return t("vocabValue", { size: format.number(s.vocab_size), level: s.cefr ?? "–" });
    return s.cefr ?? t("measured");
  };
  const placed = board.skills.filter((s) => s.position !== null);
  return (
    <Section testId="dashboard-skills" title={t("title")} description={t("description")}>
      {placed.length > 0 && <SkillsChart skills={placed} name={name} />}
      {board.skills.length === 0 && (
        <Empty>
          {t("empty")}{" "}
          <Link href="/placement" className={linkClass}>
            {t("takeTest")}
          </Link>
        </Empty>
      )}
      <ul className="flex flex-col gap-1 text-sm">
        {SKILLS.map((skill) => {
          const s = measured.get(skill);
          return (
            <li key={skill} data-testid={`dashboard-skill-${skill}`} className="flex gap-2">
              <span className="w-16 shrink-0 text-muted-foreground">{name(skill)}</span>
              <span>{s ? value(s) : t("notAssessed")}</span>
            </li>
          );
        })}
      </ul>
    </Section>
  );
}

function ErrorsSection({ board }: { board: Dashboard }) {
  const t = useTranslations("dashboard.errors");
  const locale = useLocale();
  return (
    <Section testId="dashboard-errors" title={t("title")} description={t("description")}>
      {board.errors.length > 0 ? (
        <>
          <ErrorsChart errors={board.errors} />
          <ol className="flex flex-col gap-1 text-sm">
            {board.errors.map((e) => (
              <li key={e.kc_id} className="flex justify-between gap-2">
                <Link href={learnerHref(e.kc_id)} className={linkClass}>
                  {kcName(e, locale)} <span className="text-muted-foreground">({e.cefr})</span>
                </Link>
                <span className="flex gap-3">
                  <span className="tabular-nums">{t("count", { n: e.mistakes })}</span>
                  <span className="inline-flex items-center gap-1">
                    <Link href={practiceHref(e.kc_id)} className={linkClass}>
                      {t("practice")}
                    </Link>
                    <AiBadge feature="practice_start" />
                  </span>
                </span>
              </li>
            ))}
          </ol>
        </>
      ) : (
        <Empty>
          {t("empty")}{" "}
          <Link href="/chat" className={linkClass}>
            {t("chat")}
          </Link>
        </Empty>
      )}
    </Section>
  );
}

function ActivitySection({ board }: { board: Dashboard }) {
  const t = useTranslations("dashboard.activity");
  const reviews = board.days.reduce((n, d) => n + d.reviews, 0);
  const turns = board.days.reduce((n, d) => n + d.turns, 0);
  const studied = board.days.filter((d) => d.reviews + d.turns > 0).length;
  return (
    <Section testId="dashboard-activity" title={t("title")} description={t("description")}>
      <ActivityHeatmap days={board.days} />
      <p className="text-sm" data-testid="activity-summary">
        {hasActivity(board.days) ? t("summary", { studied, reviews, turns }) : t("empty")}
      </p>
    </Section>
  );
}
