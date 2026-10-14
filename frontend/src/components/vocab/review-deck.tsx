"use client";

import { Dialog } from "@base-ui/react/dialog";
import { Bookmark, Volume2, X } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { type ReactNode, useEffect, useRef, useState } from "react";

import { useDescribeError } from "@/components/settings/use-describe-error";
import { ReadAloudBadge } from "@/components/speech/read-aloud-badge";
import { Button } from "@/components/ui/button";
import { ProgressBar } from "@/components/ui/progress";
import { Segmented } from "@/components/ui/segmented";
import { Tag } from "@/components/ui/tag";
import { ErrorText } from "@/components/ui/error-text";
import { isShortcut } from "@/lib/keyboard";
import { useReviewChoice } from "@/lib/preferences";
import { petHappy } from "@/lib/tutor-pet";
import { speakWord, useCanSpeak } from "@/lib/speech";
import { cn } from "@/lib/utils";
import {
  announceReviewed,
  cardFormat,
  formatInterval,
  judgeSpelling,
  listenOptions,
  type Rating,
  REVIEW_CHOICES,
  SUGGESTED_RATING,
} from "@/lib/vocab";
import { CatLoading, LingoCat } from "@/components/brand/lingo-cat";

import { type Answer, AnswerResult, ListenFront, SPELL_FORM, SpellFront } from "./review-fronts";
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
 * Flashcards (P1 plan §6) in an overlay over whatever page opened them (ADR 0038): a
 * blurred backdrop and the card in the middle, with two cards fanned out behind it like the
 * home page's still. The word first; recall it, then flip (Space) to see the pronunciation
 * and meanings, and rate how well you knew it (1–4). Words reviewed before can instead be
 * heard, to pick their meaning or type them (task 63); the answer is judged and a rating
 * suggested, which Enter takes.
 *
 * `onClose` runs once the closing transition is over; `onReviewAll` switches a finished
 * new-words round to the due reviews.
 */
export function ReviewDeck({
  mode,
  onClose,
  onReviewAll,
}: {
  mode: ReviewMode;
  onClose: () => void;
  onReviewAll: () => void;
}) {
  const [open, setOpen] = useState(true);
  // Focus goes to the card, not the close button, so Space flips instead of closing.
  const cardRef = useRef<HTMLDivElement>(null);
  const t = useTranslations("vocab.review");
  const describe = useDescribeError();
  const session = useReviewSession(mode);
  // Closed by the button, Esc or Back alike: the page underneath reloads its counts.
  const reviewed = useRef(0);
  useEffect(() => {
    reviewed.current = session.reviewed;
  }, [session.reviewed]);
  useEffect(
    () => () => {
      if (reviewed.current > 0) announceReviewed();
    },
    [],
  );
  const { current, flipped, suggested, flip, answer, rate } = session;
  const speakable = useCanSpeak();
  const locale = useLocale();
  const [choice, setChoice] = useReviewChoice();
  // A round of words done: the desk pet hops (ADR 0032 §4a).
  const roundDone = !session.loading && !current && session.error == null && session.reviewed > 0;
  useEffect(() => {
    if (roundDone) petHappy();
  }, [roundDone]);

  // A card is one sitting's turn: the same word can come back after a miss.
  const turn = current ? `${current.word.id}:${session.reviewed}` : "";
  const seed = current ? current.word.id * 7919 + session.reviewed : 0;
  const [answered, setAnswered] = useState<{ turn: string; answer: Answer } | null>(null);
  const result = answered?.turn === turn ? answered.answer : null;
  const [typing, setTyping] = useState({ turn: "", text: "" });
  const typed = typing.turn === turn ? typing.text : "";
  // Settled once answered, so changing the choice can't change a card being rated.
  const format =
    result?.format ??
    (current && !flipped ? cardFormat(current, choice, speakable, seed) : "recognize");
  const options = current && format === "listen" ? listenOptions(current, seed) : [];

  // Heard first: read the word as the card shows (Q63g).
  const heard = current && format !== "recognize" && !flipped ? current.word.word : null;
  useEffect(() => {
    if (heard) speakWord(heard);
  }, [heard, turn]);

  const pick = (option: string | null) => {
    if (!current) return;
    const right = option === current.gloss;
    setAnswered({ turn, answer: { format: "listen", picked: option, right } });
    answer(right ? 3 : 1);
  };
  const check = () => {
    if (!current) return;
    const text = typed.trim() ? typed : null;
    const judged = text === null ? "wrong" : judgeSpelling(text, current.word.word);
    setAnswered({ turn, answer: { format: "spell", typed: text, result: judged } });
    answer(SUGGESTED_RATING[judged]);
  };

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (!isShortcut(event)) return;
      const digit = ["1", "2", "3", "4"].indexOf(event.key);
      if (flipped) {
        if (digit >= 0) {
          event.preventDefault();
          void rate((digit + 1) as Rating, format);
        } else if ((event.key === "Enter" || event.key === " ") && suggested !== null) {
          event.preventDefault();
          void rate(suggested, format);
        }
      } else if (format === "recognize") {
        if (event.key === " ") {
          event.preventDefault();
          flip();
        }
      } else if (event.key.toLowerCase() === "r" && heard) {
        event.preventDefault();
        speakWord(heard);
      } else if (format === "listen" && digit >= 0 && options[digit] !== undefined) {
        event.preventDefault();
        pick(options[digit]);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  // Why the card isn't in the format picked.
  const note =
    choice === "recognize"
      ? null
      : !speakable
        ? t("format.cantSpeak")
        : !current || flipped
          ? null
          : current.last_review === null
            ? t("format.newFirst")
            : choice === "listen" && format === "recognize"
              ? t("format.noChoices")
              : null;

  const isNew = current && (current.status === null || current.status === "new");
  const mine = current?.source === "auto" || current?.source === "manual";

  const total = session.reviewed + session.remaining;
  const done = !session.loading && !current && session.error == null;
  // Cards fanned out behind the current one: fewer as the round runs out.
  const behind = Math.min(2, Math.max(0, session.remaining - 1));

  return (
    <Dialog.Root
      open={open}
      onOpenChange={(next) => setOpen(next)}
      onOpenChangeComplete={(next) => {
        if (!next) onClose();
      }}
    >
      <Dialog.Portal>
        <Dialog.Backdrop className="fixed inset-0 z-50 bg-foreground/25 backdrop-blur-md transition-opacity duration-200 data-ending-style:opacity-0 data-starting-style:opacity-0" />
        <Dialog.Popup
          initialFocus={cardRef}
          className="fixed inset-0 z-50 flex flex-col items-center px-4 pt-[max(12px,env(safe-area-inset-top))] pb-[max(16px,env(safe-area-inset-bottom))] outline-none transition-[opacity,scale] duration-200 data-ending-style:scale-95 data-ending-style:opacity-0 data-starting-style:scale-95 data-starting-style:opacity-0"
          data-testid="review-deck"
        >
          <Dialog.Title className="sr-only">{t("title")}</Dialog.Title>

          {/* The bar above the card: progress, the card format, close (Q75e). */}
          <div className="flex w-full max-w-[520px] shrink-0 flex-col gap-2.5">
            <div className="flex items-center gap-3">
              <div className="flex min-w-0 flex-1 flex-col gap-1.5">
                <span className="text-[13px]" data-testid="review-progress">
                  {t.rich("progress", {
                    reviewed: session.reviewed,
                    remaining: session.remaining,
                    b: (chunks) => <b className="font-semibold">{chunks}</b>,
                  })}
                </span>
                <ProgressBar value={total > 0 ? session.reviewed / total : 0} />
              </div>
              <Dialog.Close
                render={<Button variant="ghost" size="icon-sm" className="rounded-full bg-card/70" />}
                aria-label={t("close")}
                data-testid="review-close"
              >
                <X />
              </Dialog.Close>
            </div>
            <div className="flex flex-col items-center gap-1.5">
              <Segmented
                size="sm"
                label={t("format.label")}
                value={choice}
                onChange={setChoice}
                options={REVIEW_CHOICES.map((c) => ({
                  value: c,
                  label: t(`format.${c}`),
                  disabled: c !== "recognize" && !speakable,
                }))}
                data-testid="review-format"
              />
              {note && (
                <p className="text-center text-xs text-muted-foreground" data-testid="review-format-note">
                  {note}
                </p>
              )}
            </div>
          </div>

          {/* The stack. The card has a fixed height inside the viewport; a long back scrolls
              inside it, and the answer / rating bar stays at its bottom (Q75a). */}
          <div className="relative my-4 flex min-h-0 w-full max-w-[520px] flex-1 md:max-h-[640px]">
            {behind >= 2 && (
              <div
                aria-hidden
                className="absolute inset-x-6 inset-y-0 rotate-[-4deg] rounded-2xl border bg-muted/80"
              />
            )}
            {behind >= 1 && (
              <div
                aria-hidden
                className="absolute inset-x-3 inset-y-0 rotate-[2.5deg] rounded-2xl border bg-brand-soft"
              />
            )}
            <div
              className="relative flex min-h-0 w-full flex-col overflow-hidden rounded-2xl border bg-card shadow-(--shadow-pop)"
              data-testid={current ? "review-card" : undefined}
            >
              <div
                ref={cardRef}
                tabIndex={-1}
                className="flex min-h-0 flex-1 flex-col overflow-y-auto px-5 py-4 outline-none md:px-6"
              >
                {session.error != null && <ErrorText>{describe(session.error)}</ErrorText>}
                {session.loading && (
                  <div className="m-auto">
                    <CatLoading label={t("loading")} />
                  </div>
                )}

                {done && (
                  <div
                    className="m-auto flex flex-col items-center gap-3 py-4 text-center"
                    data-testid="review-done"
                  >
                    <LingoCat mood={session.reviewed > 0 ? "done" : "idle"} size={72} label="" />
                    <p className="text-lg font-bold">
                      {session.reviewed > 0 ? t("done", { reviewed: session.reviewed }) : t("nothing")}
                    </p>
                    {mode === "new" && session.reviewsDue > 0 && (
                      <p className="text-sm text-muted-foreground">
                        {t("reviewsLeft", { count: session.reviewsDue })}
                      </p>
                    )}
                    <div className="flex gap-2">
                      {mode === "new" && session.reviewsDue > 0 && (
                        <Button size="sm" onClick={onReviewAll}>
                          {t("reviewNow")}
                        </Button>
                      )}
                      <Dialog.Close render={<Button size="sm" variant="outline" />}>
                        {t("close")}
                      </Dialog.Close>
                    </div>
                  </div>
                )}

                {current && (
                  <div className="flex flex-1 flex-col gap-5">
                    <div className="flex min-h-5 gap-1.5">
                      {isNew && <Tag>{t("new")}</Tag>}
                      {mine && (
                        <Tag>
                          <Bookmark aria-hidden />
                          {t("mine")}
                        </Tag>
                      )}
                    </div>
                    {format === "listen" && !flipped ? (
                      <div className="my-auto">
                        <ListenFront word={current.word.word} options={options} onPick={pick} />
                      </div>
                    ) : format === "spell" && !flipped ? (
                      <div className="my-auto">
                        <SpellFront
                          word={current.word.word}
                          gloss={current.gloss}
                          typed={typed}
                          onType={(text) => setTyping({ turn, text })}
                          onSubmit={check}
                        />
                      </div>
                    ) : (
                      <>
                        {result && <AnswerResult answer={result} word={current.word.word} />}
                        {/* Front: the word alone, centred, to recall. Back: read top to bottom. */}
                        <div
                          className={cn(
                            "flex flex-col gap-1.5",
                            flipped ? "items-start" : "my-auto items-center pb-10 text-center",
                          )}
                        >
                          <div className="flex items-center gap-2">
                            <h2
                              className={cn(
                                "leading-tight font-bold tracking-tight break-all",
                                flipped ? "text-[32px] md:text-4xl" : "text-[44px] md:text-5xl",
                              )}
                              lang="en"
                            >
                              {current.word.word}
                            </h2>
                            {speakable && (
                              <Button
                                variant="ghost"
                                size="icon-sm"
                                aria-label={t("speak")}
                                onClick={() => speakWord(current.word.word)}
                              >
                                <Volume2 />
                              </Button>
                            )}
                            {speakable && <ReadAloudBadge />}
                          </div>
                          {flipped && current.word.phonetic && (
                            <p className="font-mono text-muted-foreground">/{current.word.phonetic}/</p>
                          )}
                          {flipped && current.mispronounced && (
                            <p
                              className="flex flex-wrap items-center gap-x-2 gap-y-1"
                              data-testid="review-mispronounced"
                            >
                              <Tag variant="warning">{t("mispronounced")}</Tag>
                              <span className="text-xs text-muted-foreground">{t("mispronouncedHint")}</span>
                            </p>
                          )}
                        </div>
                      </>
                    )}

                    {flipped && (
                      <div className="border-t pt-4 pb-1" data-testid="review-back">
                        <WordMeanings key={current.word.id} card={current} />
                      </div>
                    )}
                  </div>
                )}
              </div>

              {current && (
                <div className="shrink-0 border-t bg-card px-3 py-3">
                  {flipped ? (
                    <div
                      className="grid grid-cols-4 divide-x overflow-hidden rounded-xl border bg-card"
                      role="group"
                      aria-label={t("rateLabel")}
                    >
                      {RATINGS.map((r) => (
                        <button
                          key={r}
                          type="button"
                          disabled={session.busy}
                          onClick={() => void rate(r, format)}
                          data-suggested={r === suggested || undefined}
                          className="relative flex flex-col items-center gap-1 py-3 text-[15px] font-medium transition-colors outline-none hover:bg-muted data-suggested:bg-accent focus-visible:bg-muted focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset active:bg-accent disabled:opacity-50"
                        >
                          <span className="flex items-center gap-1.5">
                            <span aria-hidden className={cn("size-2 rounded-full", RATING_DOT[r])} />
                            {t(`ratings.${r}`)}
                          </span>
                          {/* When the word comes back if you choose this. */}
                          <span className="text-xs text-muted-foreground tabular-nums" data-testid="rating-interval">
                            {formatInterval(current.intervals[r - 1] ?? 0, locale)}
                          </span>
                          {r === suggested && (
                            <span className="absolute top-1 left-1.5 text-[10px] font-semibold text-primary">
                              {t("suggested")}
                            </span>
                          )}
                          <span
                            aria-hidden
                            className="absolute top-1 right-1.5 font-mono text-[10px] text-muted-foreground/70 max-md:hidden"
                          >
                            {r}
                          </span>
                        </button>
                      ))}
                    </div>
                  ) : format === "listen" ? (
                    <Button size="lg" variant="outline" className="w-full" onClick={() => pick(null)}>
                      {t("listen.dontKnow")}
                    </Button>
                  ) : format === "spell" ? (
                    <Button
                      size="lg"
                      variant={typed.trim() ? "default" : "outline"}
                      className="w-full"
                      type="submit"
                      form={SPELL_FORM}
                    >
                      {typed.trim() ? t("spell.check") : t("spell.dontKnow")}
                    </Button>
                  ) : (
                    <Button size="lg" className="w-full" onClick={flip}>
                      {t("flip")}
                    </Button>
                  )}
                </div>
              )}
            </div>
          </div>

          {current && (
            <p className="shrink-0 text-center text-xs text-muted-foreground max-md:hidden">
              {t.rich(
                flipped
                  ? suggested !== null
                    ? "keysSuggested"
                    : "keys"
                  : format === "listen"
                    ? "keysListen"
                    : format === "spell"
                      ? "keysSpell"
                      : "keys",
                { k: kbd },
              )}
            </p>
          )}
        </Dialog.Popup>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
