"use client";

import { GraduationCap } from "lucide-react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import { AiBadge } from "@/components/ai-badge";
import { useOpenConversation } from "@/components/chat/conversation-opener";
import { useDescribeError } from "@/components/settings/use-describe-error";
import { Button } from "@/components/ui/button";
import { Callout } from "@/components/ui/callout";
import { ErrorText } from "@/components/ui/error-text";
import { CefrTag, Tag, isCefrLevel } from "@/components/ui/tag";
import type { TutorCard } from "@/lib/cards";
import {
  type Course,
  fetchCourse,
  onLessonChanged,
  startLesson,
  testOut,
} from "@/lib/course";
import { kcName } from "@/lib/learner";
import type { Conversation } from "@/lib/types";

/**
 * The top of a lesson's conversation (ADR 0044 §5): which lesson, its state, "I already
 * know this" until it is passed, then the next lesson. The state is reloaded whenever a
 * pass quiz finishes or a turn ends.
 */
export function LessonBar({
  conversationId,
  kc,
  onCard,
}: {
  conversationId: string;
  kc: NonNullable<Conversation["focus_kc"]>;
  /** The test-out quiz card, when it lands in this conversation. */
  onCard: (card: TutorCard) => void;
}) {
  const t = useTranslations("chat.lesson");
  const tCourse = useTranslations("course");
  const locale = useLocale();
  const openConversation = useOpenConversation();
  const describe = useDescribeError();
  const [course, setCourse] = useState<Course | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    const load = () => void fetchCourse().then((c) => live && setCourse(c), () => {});
    load();
    const off = onLessonChanged(load);
    return () => {
      live = false;
      off();
    };
  }, []);

  const lesson = course?.lessons.find((l) => l.kc_id === kc.id);
  const passed = lesson?.state === "passed" || lesson?.state === "review";
  const next = passed && course?.current && course.current !== kc.id
    ? course.lessons.find((l) => l.kc_id === course.current)
    : undefined;

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (e) {
      setError(describe(e));
    } finally {
      setBusy(false);
    }
  }

  const quiz = () =>
    run(async () => {
      const { conversation, card } = await testOut(kc.id, locale);
      if (conversation.id === conversationId) onCard(card);
      else openConversation(conversation);
    });
  const goNext = (kcId: string) =>
    run(async () => {
      const { conversation } = await startLesson(kcId, locale);
      openConversation(conversation);
    });

  return (
    <Callout
      tone="neutral"
      icon={<GraduationCap aria-hidden />}
      className="mx-auto mt-3 w-[calc(100%-1.5rem)] max-w-3xl"
      data-testid="lesson-bar"
      data-state={lesson?.state}
      action={
        <span className="flex shrink-0 items-center gap-1.5">
          {next ? (
            <Button size="sm" disabled={busy} onClick={() => void goNext(next.kc_id)}>
              {t("next", { n: next.number })}
            </Button>
          ) : (
            lesson &&
            !passed && (
              <>
                <Button size="sm" variant="outline" disabled={busy} onClick={() => void quiz()}>
                  {tCourse("testOut")}
                </Button>
                <AiBadge feature="quiz_card" />
              </>
            )
          )}
          <Link
            href="/course"
            className="ml-1 text-[13px] font-medium text-primary underline-offset-2 hover:underline"
          >
            {t("course")}
          </Link>
        </span>
      }
    >
      {lesson ? t("label", { n: lesson.number, kc: kcName(kc, locale) }) : kcName(kc, locale)}{" "}
      {isCefrLevel(kc.cefr) ? <CefrTag level={kc.cefr} /> : <Tag>{kc.cefr}</Tag>}{" "}
      {lesson && <Tag variant={passed ? "success" : "outline"}>{tCourse(`state.${lesson.state}`)}</Tag>}
      {error && (
        <ErrorText size="xs" className="mt-1">
          {error}
        </ErrorText>
      )}
    </Callout>
  );
}
