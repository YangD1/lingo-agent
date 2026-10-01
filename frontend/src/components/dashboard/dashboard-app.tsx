"use client";

import {
  ArrowLeftRight,
  BookOpen,
  CircleCheck,
  Flame,
  Gauge,
  GraduationCap,
  Library,
  ListChecks,
  type LucideIcon,
  RotateCw,
} from "lucide-react";
import Link from "next/link";
import { useFormatter, useLocale, useTranslations } from "next-intl";
import { type ReactNode, useEffect, useState } from "react";

import { AiBadge } from "@/components/ai-badge";
import { useDescribeError } from "@/components/settings/use-describe-error";
import { buttonVariants } from "@/components/ui/button";
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { EmptyState, Skeleton } from "@/components/ui/empty-state";
import { CefrTag } from "@/components/ui/tag";
import {
  type Dashboard,
  fetchDashboard,
  hasActivity,
  hasGrammar,
  type SkillPoint,
} from "@/lib/dashboard";
import { CEFR_LEVELS, kcName, learnerHref, practiceHref } from "@/lib/learner";
import { cn } from "@/lib/utils";

import { ActivityHeatmap } from "./activity-heatmap";
import { BookChart } from "./book-chart";
import { ErrorsChart } from "./errors-chart";
import { GrammarChart } from "./grammar-chart";
import { SkillsChart } from "./skills-chart";
import { TodayTutor } from "./today-tutor";

/** Skills the dashboard always lists; P1 only measures grammar and vocabulary. */
const SKILLS = ["grammar", "vocab", "reading", "listening", "speaking", "writing"] as const;

const noteLinkClass = "font-medium text-primary hover:underline underline-offset-2";
const emptyButton = buttonVariants({ size: "sm", variant: "outline" });

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
      <div className="mx-auto flex max-w-5xl flex-col gap-3.5 p-4 md:gap-4 md:px-10 md:py-8">
        <h1 className="mb-1 text-[26px] font-bold tracking-tight max-md:sr-only">{t("title")}</h1>
        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}
        {!board && !error && <Loading label={t("loading")} />}
        {board && (
          <>
            <SummaryCards board={board} />
            {/* A turn counts toward today's numbers and the streak. */}
            <TodayTutor onTurnFinished={() => void load()} />
            <div className="grid items-start gap-3.5 md:grid-cols-2 md:gap-4">
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

function Loading({ label }: { label: string }) {
  return (
    <div role="status" aria-label={label} className="flex flex-col gap-4">
      <div className="grid grid-cols-2 gap-3.5 md:grid-cols-4 md:gap-4">
        {[0, 1, 2, 3].map((i) => (
          <Skeleton key={i} className="h-[102px] rounded-lg" />
        ))}
      </div>
      <Skeleton className="h-72 rounded-xl" />
    </div>
  );
}

function Section({
  title,
  description,
  action,
  testId,
  className,
  children,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
  testId: string;
  className?: string;
  children: ReactNode;
}) {
  return (
    <Card data-testid={testId} className={className}>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        {description && <CardDescription>{description}</CardDescription>}
        {action && <CardAction>{action}</CardAction>}
      </CardHeader>
      <CardContent className="flex flex-col gap-4">{children}</CardContent>
    </Card>
  );
}

function Stat({
  icon: Icon,
  label,
  value,
  muted = false,
  note,
  testId,
}: {
  icon: LucideIcon;
  label: string;
  value: ReactNode;
  /** The value is a placeholder such as "not assessed". */
  muted?: boolean;
  note?: ReactNode;
  testId: string;
}) {
  return (
    <Card size="sm" data-testid={testId} className="gap-1.5 md:[--card-px:18px] md:[--card-spacing:16px]">
      <CardContent className="flex flex-col gap-1.5">
        <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <Icon aria-hidden className="size-3.5" />
          {label}
        </span>
        <span
          className={cn(
            "text-[22px] leading-tight font-bold tracking-tight md:text-[26px]",
            muted && "text-muted-foreground",
          )}
        >
          {value}
        </span>
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
    <Link href="/placement" className={noteLinkClass}>
      {t("takeTest")}
    </Link>
  );
  return (
    <div className="grid grid-cols-2 gap-3.5 md:grid-cols-4 md:gap-4">
      <Stat
        testId="stat-level"
        icon={GraduationCap}
        label={t("level")}
        value={s.cefr ?? t("none")}
        muted={!s.cefr}
        note={s.cefr ? t("levelNote") : test}
      />
      <Stat
        testId="stat-vocab"
        icon={Library}
        label={t("vocab")}
        value={s.vocab_size === null ? "—" : t("words", { n: format.number(s.vocab_size) })}
        muted={s.vocab_size === null}
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
        icon={Flame}
        label={t("streak")}
        value={t("days", { n: s.streak_days })}
        note={
          s.studied_today ? t("studiedToday") : s.streak_days > 0 ? t("keepGoing") : t("start")
        }
      />
      <Stat
        testId="stat-today"
        icon={RotateCw}
        label={t("today")}
        value={t("reviews", { n: s.reviews_due })}
        note={
          s.reviews_due + s.new_left > 0 ? (
            <Link href="/vocab/review" className={noteLinkClass}>
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
      action={
        book && (
          <Link href="/vocab" className={buttonVariants({ size: "sm", variant: "ghost" })}>
            <ArrowLeftRight />
            {t("change")}
          </Link>
        )
      }
    >
      {book ? (
        <>
          <BookChart book={book} />
          <p className="text-[13px] text-muted-foreground" data-testid="book-summary">
            {t("summary", { ...book })}
          </p>
        </>
      ) : (
        <EmptyState
          icon={BookOpen}
          title={t("empty")}
          description={t("emptyHint")}
          action={
            <Link href="/vocab" className={emptyButton}>
              {t("choose")}
            </Link>
          }
        />
      )}
    </Section>
  );
}

function GrammarSection({ board }: { board: Dashboard }) {
  const t = useTranslations("dashboard.grammar");
  const has = hasGrammar(board.grammar);
  return (
    <Section
      testId="dashboard-grammar"
      title={t("title")}
      description={has ? t("description") : undefined}
    >
      {has ? (
        <>
          <GrammarChart grammar={board.grammar} />
          <div className="overflow-hidden rounded-lg border">
            <table className="w-full text-[13px]" data-testid="grammar-table">
              <caption className="sr-only">{t("title")}</caption>
              <thead className="bg-muted text-xs text-muted-foreground">
                <tr className="[&>th]:px-3 [&>th]:py-2 [&>th]:font-[550]">
                  <th scope="col" className="text-left">{t("level")}</th>
                  <th scope="col" className="text-right">{t("mastered")}</th>
                  <th scope="col" className="text-right">{t("learning")}</th>
                  <th scope="col" className="text-right">{t("weak")}</th>
                  <th scope="col" className="text-right">{t("unseen")}</th>
                </tr>
              </thead>
              <tbody className="font-mono tabular-nums">
                {CEFR_LEVELS.map((level) => {
                  const l = board.grammar[level];
                  return (
                    <tr key={level} className="border-t [&>*]:px-3 [&>*]:py-2">
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
          </div>
        </>
      ) : (
        <EmptyState
          icon={ListChecks}
          title={t("emptyTitle")}
          description={t("emptyHint")}
          action={
            <Link href="/chat" className={emptyButton}>
              {t("chat")}
            </Link>
          }
        />
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
  const rows = SKILLS.map((skill) => {
    const s = measured.get(skill);
    return { skill, label: name(skill), position: s?.position ?? null, cefr: s?.cefr ?? null };
  });
  return (
    <Section
      testId="dashboard-skills"
      title={t("title")}
      description={board.skills.length > 0 ? t("description") : undefined}
    >
      {board.skills.length === 0 ? (
        <EmptyState
          icon={Gauge}
          title={t("empty")}
          description={t("emptyHint")}
          action={
            <Link href="/placement" className={emptyButton}>
              {t("takeTest")}
            </Link>
          }
        />
      ) : (
        <>
          {rows.some((r) => r.position !== null) && <SkillsChart rows={rows} />}
          <ul className="grid grid-cols-2 gap-x-4 gap-y-2 border-t pt-3.5 text-[13px] sm:grid-cols-3">
            {SKILLS.map((skill) => {
              const s = measured.get(skill);
              return (
                <li key={skill} data-testid={`dashboard-skill-${skill}`} className="flex gap-1.5">
                  <span className="shrink-0 text-muted-foreground">{name(skill)}</span>
                  <span className={s ? "font-semibold" : "text-muted-foreground"}>
                    {s ? value(s) : t("notAssessed")}
                  </span>
                </li>
              );
            })}
          </ul>
        </>
      )}
    </Section>
  );
}

function ErrorsSection({ board }: { board: Dashboard }) {
  const t = useTranslations("dashboard.errors");
  const locale = useLocale();
  const has = board.errors.length > 0;
  return (
    <Section
      testId="dashboard-errors"
      title={t("title")}
      description={has ? t("description") : undefined}
    >
      {has ? (
        <>
          <ErrorsChart errors={board.errors} />
          <ol className="flex flex-col text-[13px]">
            {board.errors.map((e, i) => (
              <li
                key={e.kc_id}
                className="flex min-h-10 items-center gap-2.5 border-t py-1.5 first:border-t-0"
              >
                <span className="w-4 shrink-0 font-mono text-xs text-muted-foreground">{i + 1}</span>
                <Link
                  href={learnerHref(e.kc_id)}
                  className="min-w-0 flex-1 truncate font-medium text-primary underline-offset-2 hover:underline"
                >
                  {kcName(e, locale)}
                  <span className="sr-only"> ({e.cefr})</span>
                </Link>
                <CefrTag level={e.cefr} className="hidden sm:inline-flex" />
                <span className="shrink-0 text-xs text-muted-foreground tabular-nums">
                  {t("count", { n: e.mistakes })}
                </span>
                <span className="inline-flex shrink-0 items-center gap-1">
                  <Link
                    href={practiceHref(e.kc_id)}
                    className="font-medium text-primary underline-offset-2 hover:underline"
                  >
                    {t("practice")}
                  </Link>
                  <AiBadge feature="practice_start" />
                </span>
              </li>
            ))}
          </ol>
        </>
      ) : (
        <EmptyState
          icon={CircleCheck}
          title={t("emptyTitle")}
          description={t("empty")}
          action={
            <Link href="/chat" className={emptyButton}>
              {t("chat")}
            </Link>
          }
        />
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
      <p className="text-[13px] text-muted-foreground" data-testid="activity-summary">
        {hasActivity(board.days) ? t("summary", { studied, reviews, turns }) : t("empty")}
      </p>
    </Section>
  );
}
