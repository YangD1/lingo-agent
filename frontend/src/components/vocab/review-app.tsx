"use client";

import { ArrowLeft, Bookmark, Volume2 } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { type ReactNode, useEffect } from "react";

import { LogoMark } from "@/components/brand/logo";

import { useDescribeError } from "@/components/settings/use-describe-error";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { ProgressBar } from "@/components/ui/progress";
import { Tag } from "@/components/ui/tag";
import { isShortcut } from "@/lib/keyboard";
import { speak, useCanSpeak } from "@/lib/speech";
import { cn } from "@/lib/utils";
import type { Rating } from "@/lib/vocab";

import { type ReviewMode, useReviewSession } from "./use-review-session";

const RATINGS: readonly Rating[] = [1, 2, 3, 4];
// "Again" reads as a miss, "Good" as the usual answer; the other two stay plain.
const RATING_CLASS: Record<Rating, string> = {
  1: "border-transparent bg-destructive/10 text-destructive hover:bg-destructive/15",
  2: "bg-card hover:bg-muted",
  3: "bg-muted hover:bg-accent",
  4: "bg-card hover:bg-muted",
};

const kbd = (chunks: ReactNode) => (
  <kbd className="mx-0.5 inline-flex h-5 min-w-5 items-center justify-center rounded-[5px] border bg-card px-1 font-mono text-[11px]">
    {chunks}
  </kbd>
);

/**
 * Flashcards (P1 plan §6): the word first; recall it, then flip (Space) to see the
 * pronunciation and meanings, and rate how well you knew it (1–4).
 */
export function ReviewApp({ mode }: { mode: ReviewMode }) {
  const t = useTranslations("vocab.review");
  const describe = useDescribeError();
  const session = useReviewSession(mode);
  const { current, flipped, flip, rate } = session;
  const speakable = useCanSpeak();

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (!isShortcut(event)) return;
      if (event.key === " ") {
        event.preventDefault();
        flip();
      } else if (["1", "2", "3", "4"].includes(event.key)) {
        event.preventDefault();
        void rate(Number(event.key) as Rating);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [flip, rate]);

  const isNew = current && (current.status === null || current.status === "new");
  const mine = current?.source === "auto" || current?.source === "manual";

  const total = session.reviewed + session.remaining;

  return (
    <div className="flex flex-1 flex-col overflow-y-auto">
      <header className="grid shrink-0 grid-cols-[1fr_auto_1fr] items-center gap-3 px-4 pt-3 md:px-6">
        <Link
          href="/vocab"
          className={buttonVariants({ size: "sm", variant: "ghost", className: "justify-self-start" })}
        >
          <ArrowLeft />
          <span className="max-sm:sr-only">{t("back")}</span>
        </Link>
        <div className="flex w-44 flex-col items-center gap-1.5 sm:w-60">
          <span className="text-[13px]" data-testid="review-progress">
            {t.rich("progress", {
              reviewed: session.reviewed,
              remaining: session.remaining,
              b: (chunks) => <b className="font-semibold">{chunks}</b>,
            })}
          </span>
          <ProgressBar value={total > 0 ? session.reviewed / total : 0} />
        </div>
        <Link href="/dashboard" aria-label="Lingo Agent" className="justify-self-end max-md:hidden">
          <LogoMark />
        </Link>
      </header>

      <div className="mx-auto flex w-full max-w-[460px] flex-1 flex-col justify-center gap-4 p-4 md:pb-24">
        {session.error != null && (
          <p role="alert" className="text-sm text-destructive">
            {describe(session.error)}
          </p>
        )}
        {session.loading && (
          <p className="text-center text-sm text-muted-foreground">{t("loading")}</p>
        )}

        {!session.loading && !current && session.error == null && (
          <Card>
            <CardContent
              className="flex flex-col items-center gap-3 py-4 text-center"
              data-testid="review-done"
            >
              <p className="text-lg font-bold">
                {session.reviewed > 0
                  ? t("done", { reviewed: session.reviewed })
                  : t("nothing")}
              </p>
              {mode === "new" && session.reviewsDue > 0 && (
                <p className="text-sm text-muted-foreground">
                  {t("reviewsLeft", { count: session.reviewsDue })}
                </p>
              )}
              <div className="flex gap-2">
                {mode === "new" && session.reviewsDue > 0 && (
                  <Link href="/vocab/review" className={buttonVariants({ size: "sm" })}>
                    {t("reviewNow")}
                  </Link>
                )}
                <Link href="/vocab" className={buttonVariants({ size: "sm", variant: "outline" })}>
                  {t("back")}
                </Link>
              </div>
            </CardContent>
          </Card>
        )}

        {current && (
          <Card data-testid="review-card" className="rounded-2xl">
            <CardContent className="flex flex-col items-center gap-5 py-2 text-center">
              <div className="flex min-h-5 gap-1.5 self-start">
                {isNew && <Tag>{t("new")}</Tag>}
                {mine && (
                  <Tag>
                    <Bookmark aria-hidden />
                    {t("mine")}
                  </Tag>
                )}
              </div>
              <div className="flex flex-col items-center gap-2 py-4">
                <div className="flex items-center gap-2">
                  <h1
                    className="text-[44px] leading-tight font-bold tracking-tight break-all md:text-5xl"
                    lang="en"
                  >
                    {current.word.word}
                  </h1>
                  {speakable && (
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      aria-label={t("speak")}
                      onClick={() => speak(current.word.word)}
                    >
                      <Volume2 />
                    </Button>
                  )}
                </div>
                {flipped && current.word.phonetic && (
                  <p className="font-mono text-muted-foreground">/{current.word.phonetic}/</p>
                )}
              </div>

              {flipped ? (
                <div
                  className="flex w-full flex-col gap-2 border-t pt-5 pb-2"
                  data-testid="review-back"
                >
                  <p className="text-lg whitespace-pre-line">{current.word.translation}</p>
                  {current.word.definition && (
                    <p className="text-sm whitespace-pre-line text-muted-foreground" lang="en">
                      {current.word.definition}
                    </p>
                  )}
                </div>
              ) : (
                <Button size="lg" className="mb-2 w-44" onClick={flip}>
                  {t("flip")}
                </Button>
              )}
            </CardContent>
          </Card>
        )}

        {current && flipped && (
          <div className="grid grid-cols-4 gap-2" role="group" aria-label={t("rateLabel")}>
            {RATINGS.map((r) => (
              <Button
                key={r}
                variant="outline"
                disabled={session.busy}
                onClick={() => void rate(r)}
                className={cn("h-auto flex-col gap-1 py-2.5 md:h-auto", RATING_CLASS[r])}
              >
                {t(`ratings.${r}`)}
                <span className="inline-flex h-4 min-w-4 items-center justify-center rounded-[4px] border bg-card px-1 font-mono text-[10px] text-muted-foreground">
                  {r}
                </span>
              </Button>
            ))}
          </div>
        )}
        {current && (
          <p className="text-center text-xs text-muted-foreground max-md:hidden">
            {t.rich("keys", { k: kbd })}
          </p>
        )}
      </div>
    </div>
  );
}
