"use client";

import { ChevronDown, Lock } from "lucide-react";
import { useRouter } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import { AiBadge } from "@/components/ai-badge";
import { CatLoading } from "@/components/brand/lingo-cat";
import { useDescribeError } from "@/components/settings/use-describe-error";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorText } from "@/components/ui/error-text";
import { ProgressBar } from "@/components/ui/progress";
import { CefrTag, Tag } from "@/components/ui/tag";
import {
  type Course,
  courseChatHref,
  fetchCourse,
  type Lesson,
  openLevel,
  progress,
  startLesson,
  testOut,
} from "@/lib/course";
import { CEFR_LEVELS, type CefrLevel, kcName } from "@/lib/learner";
import { cn } from "@/lib/utils";

const STATE_TONE: Record<Lesson["state"], "success" | "warning" | "brand" | "outline" | "default"> = {
  passed: "success",
  review: "warning",
  learning: "brand",
  available: "outline",
  locked: "default",
};

/**
 * The grammar course (ADR 0044 §6): one lesson per grammar point, by level, with its
 * state from the learner model. "Start" opens the lesson's conversation, where the
 * tutor speaks first; a locked lesson can be tested out of with a pass quiz.
 */
export function CourseApp() {
  const t = useTranslations("course");
  const tNav = useTranslations("nav");
  const locale = useLocale();
  const router = useRouter();
  const describe = useDescribeError();
  const [course, setCourse] = useState<Course | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [actionError, setActionError] = useState<{ kc: string; text: string } | null>(null);
  const [open, setOpen] = useState<Set<CefrLevel> | null>(null);

  useEffect(() => {
    fetchCourse().then(
      (c) => {
        setCourse(c);
        setOpen(new Set([openLevel(c)]));
      },
      (e: unknown) => setError(describe(e)),
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps -- once
  }, []);

  async function go(kcId: string, how: "start" | "testOut") {
    setBusy(kcId);
    setActionError(null);
    try {
      const { conversation } = await (how === "start" ? startLesson : testOut)(kcId, locale);
      router.push(courseChatHref(conversation.id));
    } catch (e) {
      setActionError({ kc: kcId, text: describe(e) });
      setBusy(null);
    }
  }

  const byId = new Map(course?.lessons.map((l) => [l.kc_id, l]));
  const current = course?.current ? byId.get(course.current) : undefined;
  const done = course ? progress(course) : null;

  return (
    <div className="pet-safe flex-1 overflow-y-auto">
      <div className="mx-auto flex max-w-3xl flex-col gap-3.5 p-4 md:gap-4 md:px-10 md:py-8">
        <h1 className="text-[26px] font-bold tracking-tight max-md:sr-only">{tNav("course")}</h1>
        {error && <EmptyState tone="error" title={error} />}
        {!course && !error && <CatLoading label={t("loading")} />}
        {course && done && (
          <>
            <Card data-testid="course-current">
              <CardHeader>
                <CardTitle>
                  {current
                    ? t("continue", { n: current.number, name: kcName(current, locale) })
                    : t("allDone")}
                </CardTitle>
                <CardDescription>
                  {t("progress", { passed: done.passed, total: done.total })}
                  {course.level ? "" : ` · ${t("noPlacement")}`}
                </CardDescription>
              </CardHeader>
              {current && (
                <CardContent className="flex flex-wrap items-center gap-2">
                  <Button disabled={busy !== null} onClick={() => void go(current.kc_id, "start")}>
                    {current.state === "learning" ? t("resume") : t("start")}
                  </Button>
                  <AiBadge feature={["lesson_start", "quiz_card"]} />
                  {actionError?.kc === current.kc_id && (
                    <ErrorText size="xs">{actionError.text}</ErrorText>
                  )}
                </CardContent>
              )}
            </Card>
            {CEFR_LEVELS.map((level) => {
              const lessons = course.lessons.filter((l) => l.cefr === level);
              if (lessons.length === 0) return null;
              const expanded = open?.has(level) ?? false;
              const passed = lessons.filter((l) => l.state === "passed" || l.state === "review").length;
              return (
                <section key={level} className="flex flex-col gap-2" data-testid={`course-level-${level}`}>
                  <button
                    type="button"
                    aria-expanded={expanded}
                    className="flex items-center gap-2 rounded-md py-1 text-left text-sm font-semibold outline-none focus-visible:outline-2 focus-visible:outline-ring"
                    onClick={() =>
                      setOpen((all) => {
                        const next = new Set(all);
                        if (next.has(level)) next.delete(level);
                        else next.add(level);
                        return next;
                      })
                    }
                  >
                    <ChevronDown
                      aria-hidden
                      className={cn("size-4 transition-transform", !expanded && "-rotate-90")}
                    />
                    <CefrTag level={level} />
                    <span className="font-normal text-muted-foreground">
                      {t("levelProgress", { passed, total: lessons.length })}
                    </span>
                  </button>
                  {expanded && (
                    <ol className="flex flex-col gap-1.5">
                      {lessons.map((lesson) => (
                        <LessonRow
                          key={lesson.kc_id}
                          lesson={lesson}
                          current={lesson.kc_id === course.current}
                          blockers={lesson.blocked_by.map((id) => byId.get(id)).filter((l) => l !== undefined)}
                          busy={busy !== null}
                          error={actionError?.kc === lesson.kc_id ? actionError.text : null}
                          onStart={() => void go(lesson.kc_id, "start")}
                          onTestOut={() => void go(lesson.kc_id, "testOut")}
                        />
                      ))}
                    </ol>
                  )}
                </section>
              );
            })}
          </>
        )}
      </div>
    </div>
  );
}

function LessonRow({
  lesson,
  current,
  blockers,
  busy,
  error,
  onStart,
  onTestOut,
}: {
  lesson: Lesson;
  current: boolean;
  blockers: Lesson[];
  busy: boolean;
  error: string | null;
  onStart: () => void;
  onTestOut: () => void;
}) {
  const t = useTranslations("course");
  const locale = useLocale();
  const locked = lesson.state === "locked";
  return (
    <li
      className={cn(
        "flex flex-col gap-2 rounded-lg border bg-card px-3.5 py-3 text-sm",
        current && "border-primary/50",
      )}
      data-testid="course-lesson"
      data-kc={lesson.kc_id}
      data-state={lesson.state}
    >
      <div className="flex items-center gap-3">
        <span className="w-7 shrink-0 font-mono text-xs text-muted-foreground tabular-nums">
          {lesson.number}
        </span>
        <span className={cn("min-w-0 flex-1 truncate font-medium", locked && "text-muted-foreground")}>
          {locked && <Lock aria-hidden className="mr-1 inline size-3.5 align-[-2px]" />}
          {kcName(lesson, locale)}
        </span>
        <Tag variant={STATE_TONE[lesson.state]}>{t(`state.${lesson.state}`)}</Tag>
      </div>
      <div className="flex items-center gap-3 pl-10">
        <ProgressBar value={lesson.p_mastery} thin className="max-w-40 flex-1" />
        <span className="sr-only">{t("mastery", { pct: Math.round(lesson.p_mastery * 100) })}</span>
        {lesson.quiz_score !== null && (
          <span className="text-xs text-muted-foreground">
            {t("quizScore", { pct: Math.round(lesson.quiz_score * 100) })}
          </span>
        )}
        <span className="ml-auto flex items-center gap-1.5">
          {locked ? (
            <>
              <Button size="sm" variant="outline" disabled={busy} onClick={onTestOut}>
                {t("testOut")}
              </Button>
              <AiBadge feature="quiz_card" />
            </>
          ) : (
            <Button size="sm" variant={current ? "default" : "outline"} disabled={busy} onClick={onStart}>
              {lesson.state === "learning"
                ? t("resume")
                : lesson.state === "passed" || lesson.state === "review"
                  ? t("again")
                  : t("start")}
            </Button>
          )}
        </span>
      </div>
      {locked && blockers.length > 0 && (
        <p className="pl-10 text-xs text-muted-foreground">
          {t("blockedBy", { names: blockers.map((b) => kcName(b, locale)).join(t("separator")) })}
        </p>
      )}
      {error && (
        <ErrorText size="xs" className="pl-10">
          {error}
        </ErrorText>
      )}
    </li>
  );
}
