"use client";

import { Dialog } from "@base-ui/react/dialog";
import { Bookmark, CircleCheck, Volume2, X } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { type PointerEvent, type ReactNode, useEffect, useLayoutEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { useDescribeError } from "@/components/settings/use-describe-error";
import { ReadAloudBadge } from "@/components/speech/read-aloud-badge";
import { Button } from "@/components/ui/button";
import { ProgressBar } from "@/components/ui/progress";
import { Segmented } from "@/components/ui/segmented";
import { Toaster } from "@/components/ui/sonner";
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
  type Card,
  unmarkKnown,
} from "@/lib/vocab";
import { CatLoading, LingoCat } from "@/components/brand/lingo-cat";

import { canAnimate, comeBack, flyOff, rise, settle, turnAway, turnBack } from "./deck-motion";
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

// The deck's own toaster: one outside the dialog would count as a click outside and close it.
const DECK_TOASTER = "review-deck";

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
  // Focus goes to the card's body, not the close button, so Space flips instead of closing.
  const bodyRef = useRef<HTMLDivElement>(null);
  // The card that turns, flies off and rises (deck-motion.ts).
  const faceRef = useRef<HTMLDivElement>(null);
  // A turn or a rating under way: input waits for it.
  const moving = useRef(false);
  const t = useTranslations("vocab.review");
  const describe = useDescribeError();
  const session = useReviewSession(mode);
  // Closed by the button, Esc or Back alike: the page underneath reloads its counts.
  const changed = useRef(false);
  useEffect(() => {
    if (session.reviewed > 0 || session.marked !== 0) changed.current = true;
  }, [session.reviewed, session.marked]);
  // Sonner keeps toasts in a global store and shows them again to the next toaster: the
  // next round's deck would offer to undo this one's marks.
  const toasts = useRef(new Set<string | number>());
  useEffect(
    () => () => {
      if (changed.current) announceReviewed();
      for (const id of toasts.current) toast.dismiss(id);
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
  // ...and the pile gathers up under the last card, which settles with a pop.
  useLayoutEffect(() => {
    if (roundDone && canAnimate(faceRef.current)) settle(faceRef.current);
  }, [roundDone]);

  // A card is one sitting's turn: the same word can come back after a miss.
  const turn = current ? `${current.word.id}:${session.shown}` : "";
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

  // Turning over: the face goes edge-on, the back is put in, and the layout effect below
  // brings it round once it is on the page.
  const turning = useRef(false);
  const turned = useRef(false);
  // A rating keyed while the card turns (Space, then 3 at once) is kept for when it is round.
  const queued = useRef<Rating | "suggested" | null>(null);
  const turnOver = (show: () => void) => {
    const face = faceRef.current;
    if (moving.current) return;
    if (!canAnimate(face)) return show();
    moving.current = true;
    turning.current = true;
    void turnAway(face).then(() => {
      turned.current = true;
      show();
    });
  };

  // Rating: the card flies off while the rating saves, then the next one rises in its place.
  const flying = useRef(false);
  const rateCard = async (rating: Rating) => {
    const face = faceRef.current;
    if (turning.current) {
      queued.current = rating;
      return;
    }
    if (!flipped || session.busy || moving.current) return;
    if (!canAnimate(face)) {
      await rate(rating, format);
      return;
    }
    moving.current = true;
    flying.current = true;
    flyOff(face, rating === 1 ? -1 : 1);
    const saved = await rate(rating, format);
    if (!saved && flying.current) {
      // Not saved: the same card is still up, so it comes back to be rated again.
      flying.current = false;
      moving.current = false;
      comeBack(face);
    }
  };
  // Known (task 120): the card goes as if rated, without a rating; the toast can undo it.
  const markKnown = async () => {
    const face = faceRef.current;
    if (!current || session.busy || moving.current) return;
    const animate = canAnimate(face);
    if (animate) {
      moving.current = true;
      flying.current = true;
      flyOff(face, 1);
    }
    const card = await session.markKnown();
    if (!card) {
      if (animate && flying.current) {
        flying.current = false;
        moving.current = false;
        comeBack(face);
      }
      return;
    }
    const id = toast(t("known.marked"), {
      toasterId: DECK_TOASTER,
      description: t("known.whereBack"),
      action: { label: t("known.undo"), onClick: () => void undoKnown(card) },
    });
    toasts.current.add(id);
  };
  const undoKnown = async (card: Card) => {
    try {
      await unmarkKnown(card.word.id);
      session.putBack(card);
    } catch (e) {
      toasts.current.add(toast.error(describe(e), { toasterId: DECK_TOASTER }));
    }
  };

  // The turned card is up: bring it round, then take a rating keyed meanwhile.
  useLayoutEffect(() => {
    if (!turned.current) return;
    turned.current = false;
    turning.current = false;
    moving.current = false;
    if (faceRef.current) turnBack(faceRef.current);
    const wanted = queued.current === "suggested" ? suggested : queued.current;
    queued.current = null;
    if (wanted !== null) void rateCard(wanted);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- runs once the turned card is up
  }, [flipped]);
  const done = !session.loading && !current && session.error == null;
  useLayoutEffect(() => {
    if (!flying.current) return;
    flying.current = false;
    moving.current = false;
    if (faceRef.current) rise(faceRef.current);
  }, [turn, done]);

  const pick = (option: string | null) => {
    if (!current || moving.current) return;
    const right = option === current.gloss;
    setAnswered({ turn, answer: { format: "listen", picked: option, right } });
    turnOver(() => answer(right ? 3 : 1));
  };
  const check = () => {
    if (!current || moving.current) return;
    const text = typed.trim() ? typed : null;
    const judged = text === null ? "wrong" : judgeSpelling(text, current.word.word);
    setAnswered({ turn, answer: { format: "spell", typed: text, result: judged } });
    turnOver(() => answer(SUGGESTED_RATING[judged]));
  };

  // Phones (Q75c): on the back, swipe left for Again, right for Good. Touch and pen only,
  // and only sideways; up and down still scrolls the card.
  const drag = useRef<{ id: number; x: number; y: number; dx: number; on: boolean } | null>(null);
  const againHint = useRef<HTMLSpanElement>(null);
  const goodHint = useRef<HTMLSpanElement>(null);
  const swipeDistance = () => Math.min(120, (faceRef.current?.offsetWidth ?? 400) * 0.3);
  const showHints = (dx: number) => {
    const reach = Math.min(1, Math.abs(dx) / swipeDistance());
    if (againHint.current) againHint.current.style.opacity = String(dx < 0 ? reach : 0);
    if (goodHint.current) goodHint.current.style.opacity = String(dx > 0 ? reach : 0);
  };
  const onPointerDown = (event: PointerEvent<HTMLDivElement>) => {
    if (event.pointerType === "mouse" || !flipped || session.busy || moving.current) return;
    if ((event.target as Element).closest("button, a, input, textarea, summary, [role=button]")) return;
    drag.current = { id: event.pointerId, x: event.clientX, y: event.clientY, dx: 0, on: false };
  };
  const onPointerMove = (event: PointerEvent<HTMLDivElement>) => {
    const d = drag.current;
    const face = faceRef.current;
    if (!d || event.pointerId !== d.id || !face) return;
    const dx = event.clientX - d.x;
    if (!d.on) {
      if (Math.abs(dx) < 10) return;
      if (Math.abs(event.clientY - d.y) > Math.abs(dx)) {
        drag.current = null;
        return;
      }
      d.on = true;
      face.setPointerCapture(event.pointerId);
    }
    d.dx = dx;
    face.style.transform = `translateX(${dx}px) rotate(${dx / 18}deg)`;
    showHints(dx);
  };
  const onPointerEnd = (event: PointerEvent<HTMLDivElement>) => {
    const d = drag.current;
    if (!d || event.pointerId !== d.id) return;
    drag.current = null;
    showHints(0);
    const face = faceRef.current;
    if (!d.on || !face) return;
    if (event.type === "pointerup" && Math.abs(d.dx) >= swipeDistance()) void rateCard(d.dx < 0 ? 1 : 3);
    else comeBack(face);
  };

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (!isShortcut(event)) return;
      const digit = ["1", "2", "3", "4"].indexOf(event.key);
      if (turning.current) {
        if (digit >= 0) {
          event.preventDefault();
          queued.current = (digit + 1) as Rating;
        } else if (event.key === "Enter") {
          event.preventDefault();
          queued.current = "suggested";
        }
      } else if (flipped) {
        if (digit >= 0) {
          event.preventDefault();
          void rateCard((digit + 1) as Rating);
        } else if ((event.key === "Enter" || event.key === " ") && suggested !== null) {
          event.preventDefault();
          void rateCard(suggested);
        }
      } else if (format === "recognize") {
        if (event.key === " ") {
          event.preventDefault();
          turnOver(flip);
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
          initialFocus={bodyRef}
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
            {/* The pile: as the round runs out its cards straighten and slip under. */}
            <div
              aria-hidden
              className={cn(
                "absolute inset-x-6 inset-y-0 rounded-2xl border bg-muted/80 transition-[rotate,opacity,scale] duration-500 motion-reduce:transition-none",
                behind >= 2 ? "rotate-[-4deg]" : "scale-95 rotate-0 opacity-0",
              )}
            />
            <div
              aria-hidden
              className={cn(
                "absolute inset-x-3 inset-y-0 rounded-2xl border bg-brand-soft transition-[rotate,opacity,scale] duration-500 motion-reduce:transition-none",
                behind >= 1 ? "rotate-[2.5deg]" : "scale-95 rotate-0 opacity-0",
              )}
            />
            <div
              ref={faceRef}
              onPointerDown={onPointerDown}
              onPointerMove={onPointerMove}
              onPointerUp={onPointerEnd}
              onPointerCancel={onPointerEnd}
              className={cn(
                "relative flex min-h-0 w-full flex-col overflow-hidden rounded-2xl border bg-card shadow-(--shadow-pop) will-change-transform",
                flipped && "touch-pan-y touch-pinch-zoom",
              )}
              data-testid={current ? "review-card" : undefined}
            >
              {/* What letting go of a swipe would rate. */}
              <span
                ref={againHint}
                aria-hidden
                className="pointer-events-none absolute top-4 right-4 z-10 rotate-6 rounded-lg border-2 border-destructive px-2 py-0.5 text-sm font-bold text-destructive opacity-0"
              >
                {t("ratings.1")}
              </span>
              <span
                ref={goodHint}
                aria-hidden
                className="pointer-events-none absolute top-4 left-4 z-10 -rotate-6 rounded-lg border-2 border-success px-2 py-0.5 text-sm font-bold text-success opacity-0"
              >
                {t("ratings.3")}
              </span>
              <div
                ref={bodyRef}
                tabIndex={-1}
                // A scroller sets its own touch-action for touches inside it, so the swipe
                // needs it here too, not only on the card.
                className={cn(
                  "flex min-h-0 flex-1 flex-col overflow-y-auto px-5 py-4 outline-none md:px-6",
                  flipped && "touch-pan-y touch-pinch-zoom",
                )}
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
                    <div className="flex min-h-5 items-center gap-1.5">
                      {isNew && <Tag>{t("new")}</Tag>}
                      {mine && (
                        <Tag>
                          <Bookmark aria-hidden />
                          {t("mine")}
                        </Tag>
                      )}
                      <Button
                        variant="ghost"
                        size="xs"
                        className="-my-1 ml-auto text-muted-foreground"
                        title={t("known.markHint")}
                        disabled={session.busy}
                        onClick={() => void markKnown()}
                        data-testid="review-known"
                      >
                        <CircleCheck />
                        {t("known.mark")}
                      </Button>
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
                          onClick={() => void rateCard(r)}
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
                    <Button size="lg" className="w-full" onClick={() => turnOver(flip)}>
                      {t("flip")}
                    </Button>
                  )}
                </div>
              )}
            </div>
          </div>

          {current && flipped && (
            <p className="shrink-0 text-center text-xs text-muted-foreground md:hidden" data-testid="review-swipe-hint">
              {t("swipe", { again: t("ratings.1"), good: t("ratings.3") })}
            </p>
          )}
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
          <Toaster id={DECK_TOASTER} position="bottom-center" />
        </Dialog.Popup>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
