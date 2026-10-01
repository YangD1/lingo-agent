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
import { WordMeanings } from "./word-meanings";

const RATINGS: readonly Rating[] = [1, 2, 3, 4];
// A dot per rating, from a miss to easy: red, amber, green, the chart's grey-blue.
const RATING_DOT: Record<Rating, string> = {
  1: "bg-destructive",
  2: "bg-chart-2",
  3: "bg-success",
  4: "bg-chart-4",
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
    // The card scrolls on its own; the answer / rating bar stays at the bottom of the screen.
    <div className="flex min-h-0 flex-1 flex-col">
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

      <div className="flex min-h-0 flex-1 overflow-y-auto">
        {/* m-auto centres a short card and still lets a long one scroll from its top. */}
        <div className="m-auto flex w-full max-w-[520px] flex-col gap-4 p-4">
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
              <CardContent className="flex flex-col gap-5 py-2">
                <div className="flex min-h-5 gap-1.5">
                  {isNew && <Tag>{t("new")}</Tag>}
                  {mine && (
                    <Tag>
                      <Bookmark aria-hidden />
                      {t("mine")}
                    </Tag>
                  )}
                </div>
                {/* Front: the word alone, centred, to recall. Back: read top to bottom. */}
                <div
                  className={cn(
                    "flex flex-col gap-1.5",
                    flipped ? "items-start" : "items-center py-10 text-center",
                  )}
                >
                  <div className="flex items-center gap-2">
                    <h1
                      className={cn(
                        "leading-tight font-bold tracking-tight break-all",
                        flipped ? "text-[32px] md:text-4xl" : "text-[44px] md:text-5xl",
                      )}
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

                {flipped && (
                  <div className="border-t pt-4 pb-1" data-testid="review-back">
                    <WordMeanings key={current.word.id} word={current.word} />
                  </div>
                )}
              </CardContent>
            </Card>
          )}
        </div>
      </div>

      {current && (
        <footer className="shrink-0 border-t bg-background/95 px-4 pt-3 pb-[max(12px,env(safe-area-inset-bottom))]">
          <div className="mx-auto flex w-full max-w-[520px] flex-col gap-2">
            {flipped ? (
              <div
                className="grid grid-cols-4 divide-x overflow-hidden rounded-xl border bg-card shadow-(--shadow-lift)"
                role="group"
                aria-label={t("rateLabel")}
              >
                {RATINGS.map((r) => (
                  <button
                    key={r}
                    type="button"
                    disabled={session.busy}
                    onClick={() => void rate(r)}
                    className="relative flex flex-col items-center gap-1 py-3 text-[15px] font-medium transition-colors outline-none hover:bg-muted focus-visible:bg-muted focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset active:bg-accent disabled:opacity-50"
                  >
                    <span className="flex items-center gap-1.5">
                      <span aria-hidden className={cn("size-2 rounded-full", RATING_DOT[r])} />
                      {t(`ratings.${r}`)}
                    </span>
                    <span
                      aria-hidden
                      className="absolute top-1 right-1.5 font-mono text-[10px] text-muted-foreground/70 max-md:hidden"
                    >
                      {r}
                    </span>
                  </button>
                ))}
              </div>
            ) : (
              <Button size="lg" className="w-full" onClick={flip}>
                {t("flip")}
              </Button>
            )}
            <p className="text-center text-xs text-muted-foreground max-md:hidden">
              {t.rich("keys", { k: kbd })}
            </p>
          </div>
        </footer>
      )}
    </div>
  );
}
