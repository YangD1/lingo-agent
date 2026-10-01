"use client";

import { Volume2 } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { useEffect } from "react";

import { useDescribeError } from "@/components/settings/use-describe-error";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { isShortcut } from "@/lib/keyboard";
import { speak, useCanSpeak } from "@/lib/speech";
import type { Rating } from "@/lib/vocab";

import { type ReviewMode, useReviewSession } from "./use-review-session";

const RATINGS: readonly Rating[] = [1, 2, 3, 4];

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

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="mx-auto flex max-w-xl flex-col gap-4 p-4 md:p-8">
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <span data-testid="review-progress">
            {t("progress", { reviewed: session.reviewed, remaining: session.remaining })}
          </span>
          <Link
            href="/vocab"
            className={buttonVariants({ size: "sm", variant: "ghost", className: "ml-auto" })}
          >
            {t("back")}
          </Link>
        </div>
        {session.error != null && (
          <p role="alert" className="text-sm text-destructive">
            {describe(session.error)}
          </p>
        )}
        {session.loading && <p className="text-sm text-muted-foreground">{t("loading")}</p>}

        {!session.loading && !current && session.error == null && (
          <Card>
            <CardContent className="flex flex-col gap-3" data-testid="review-done">
              <p>
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
          <Card data-testid="review-card">
            <CardContent className="flex flex-col items-center gap-4 py-6 text-center">
              <div className="flex gap-2 text-xs text-muted-foreground">
                {isNew && <span>{t("new")}</span>}
                {mine && <span>{t("mine")}</span>}
              </div>
              <div className="flex items-center gap-2">
                <h1 className="text-4xl font-semibold" lang="en">
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

              {flipped ? (
                <div className="flex w-full flex-col gap-3 text-left" data-testid="review-back">
                  {current.word.phonetic && (
                    <p className="text-center text-muted-foreground">/{current.word.phonetic}/</p>
                  )}
                  <p className="whitespace-pre-line">{current.word.translation}</p>
                  {current.word.definition && (
                    <p className="text-sm whitespace-pre-line text-muted-foreground" lang="en">
                      {current.word.definition}
                    </p>
                  )}
                </div>
              ) : (
                <Button variant="outline" onClick={flip}>
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
                variant={r === 1 ? "destructive" : r === 3 ? "default" : "outline"}
                disabled={session.busy}
                onClick={() => void rate(r)}
              >
                {t(`ratings.${r}`)}
                <span className="text-xs opacity-60">{r}</span>
              </Button>
            ))}
          </div>
        )}
        {current && <p className="text-center text-xs text-muted-foreground">{t("keys")}</p>}
      </div>
    </div>
  );
}
