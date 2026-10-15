"use client";

import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import { buttonVariants } from "@/components/ui/button";
import { Card, CardAction, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { type Course, fetchCourse, progress } from "@/lib/course";
import { kcName } from "@/lib/learner";

/**
 * The course entry next to today's plan (ADR 0044 §6): the current lesson and x / y
 * passed, linking to /course. No model call until a lesson opens there: no AI badge.
 * Hidden while loading or on error; the course page shows its own.
 */
export function CourseEntry() {
  const t = useTranslations("course");
  const locale = useLocale();
  const [course, setCourse] = useState<Course | null>(null);

  useEffect(() => {
    fetchCourse().then(setCourse, () => {});
  }, []);

  if (!course) return null;
  const current = course.lessons.find((l) => l.kc_id === course.current);
  const done = progress(course);
  return (
    <Card size="sm" data-testid="course-entry">
      <CardHeader>
        <CardTitle>
          {current ? t("continue", { n: current.number, name: kcName(current, locale) }) : t("allDone")}
        </CardTitle>
        <CardDescription>{t("progress", { passed: done.passed, total: done.total })}</CardDescription>
        <CardAction>
          <Link href="/course" className={buttonVariants({ size: "sm", variant: "outline" })}>
            {t("open")}
          </Link>
        </CardAction>
      </CardHeader>
    </Card>
  );
}
