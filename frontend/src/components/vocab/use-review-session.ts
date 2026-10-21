"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import {
  type Card,
  fetchQueue,
  markKnown as markCardKnown,
  type Rating,
  rate as rateCard,
  type ReviewFormat,
} from "@/lib/vocab";

export type ReviewMode = "all" | "new";

export type ReviewSession = {
  /** Null while loading, and once there is nothing left. */
  current: Card | null;
  loading: boolean;
  /** The back of the card is showing; rating is possible only then. */
  flipped: boolean;
  /**
   * The rating the answer suggests on a listening or spelling card (Q63d); null on a
   * plain card, or when there is no answer yet.
   */
  suggested: Rating | null;
  /** A rating is being saved. */
  busy: boolean;
  /** Cards rated in this session. */
  reviewed: number;
  /** Cards marked known in this session, less those put back. */
  marked: number;
  /** Counts every card brought up, so a card back after a miss or an undo is a new turn. */
  shown: number;
  /** Cards still waiting, counting reviews beyond the page the server sent. */
  remaining: number;
  /** When done in `new` mode: reviews that are due. */
  reviewsDue: number;
  error: unknown;
  flip: () => void;
  /** Turns the card over after an answer, suggesting a rating. */
  answer: (suggested: Rating) => void;
  /** Resolves true once the rating is saved and the next card is up. */
  rate: (rating: Rating, format?: ReviewFormat) => Promise<boolean>;
  /**
   * Marks the current card known (task 120): it is skipped, not rated, and never comes
   * back. Resolves to the card once saved and the next one is up, else null.
   */
  markKnown: () => Promise<Card | null>;
  /** Shows a card again first, after its known mark was taken back. */
  putBack: (card: Card) => void;
};

type Batch = { cards: Card[]; beyond: number; reviewsDue: number };

async function nextBatch(mode: ReviewMode): Promise<Batch> {
  const queue = await fetchQueue(mode);
  const cards = mode === "new" ? queue.new : [...queue.reviews, ...queue.new];
  const beyond = mode === "new" ? 0 : queue.reviews_due - queue.reviews.length;
  return { cards, beyond, reviewsDue: queue.reviews_due };
}

/**
 * One sitting of flashcards (P1 plan §6): due reviews, then new words. Each card is shown,
 * flipped, and rated; the rating goes to FSRS on the server. When the cards run out the
 * queue is asked again, since cards failed a moment ago are due again within minutes (and
 * reviews beyond the first page come then); the session ends when it comes back empty.
 */
export function useReviewSession(mode: ReviewMode): ReviewSession {
  const [cards, setCards] = useState<Card[]>([]);
  const [beyond, setBeyond] = useState(0);
  const [reviewsDue, setReviewsDue] = useState(0);
  const [loading, setLoading] = useState(true);
  const [flipped, setFlipped] = useState(false);
  const [suggested, setSuggested] = useState<Rating | null>(null);
  const [busy, setBusy] = useState(false);
  const [reviewed, setReviewed] = useState(0);
  const [marked, setMarked] = useState(0);
  const [shown, setShown] = useState(0);
  const [error, setError] = useState<unknown>(null);
  // When the current card was shown: how long recall took is logged with the rating.
  const shownAt = useRef(0);

  const apply = useCallback((batch: Batch) => {
    setCards(batch.cards);
    setBeyond(batch.beyond);
    setReviewsDue(batch.reviewsDue);
    setLoading(false);
    shownAt.current = performance.now();
  }, []);

  useEffect(() => {
    nextBatch(mode).then(apply, (e: unknown) => {
      setError(e);
      setLoading(false);
    });
  }, [mode, apply]);

  const current = cards[0] ?? null;

  const flip = useCallback(() => {
    if (current) setFlipped(true);
  }, [current]);

  const answer = useCallback(
    (rating: Rating) => {
      if (!current || flipped) return;
      setSuggested(rating);
      setFlipped(true);
    },
    [current, flipped],
  );

  // The current card is done with: the next one comes up, or the queue is asked again.
  const advance = useCallback(async () => {
    setFlipped(false);
    setSuggested(null);
    setShown((n) => n + 1);
    const rest = cards.slice(1);
    if (rest.length) {
      setCards(rest);
      shownAt.current = performance.now();
    } else {
      setCards([]);
      setLoading(true);
      apply(await nextBatch(mode));
    }
  }, [cards, mode, apply]);

  const rate = useCallback(
    async (rating: Rating, format: ReviewFormat = "recognize") => {
      if (!current || !flipped || busy) return false;
      setBusy(true);
      setError(null);
      try {
        await rateCard(
          current.word.id,
          rating,
          Math.round(performance.now() - shownAt.current),
          format,
        );
        setReviewed((n) => n + 1);
        await advance();
        return true;
      } catch (e) {
        setError(e);
        setLoading(false);
        return false;
      } finally {
        setBusy(false);
      }
    },
    [current, flipped, busy, advance],
  );

  const markKnown = useCallback(async () => {
    if (!current || busy) return null;
    setBusy(true);
    setError(null);
    try {
      await markCardKnown(current.word.id);
      setMarked((n) => n + 1);
      await advance();
      return current;
    } catch (e) {
      setError(e);
      setLoading(false);
      return null;
    } finally {
      setBusy(false);
    }
  }, [current, busy, advance]);

  const putBack = useCallback((card: Card) => {
    setCards((now) => [card, ...now.filter((c) => c.word.id !== card.word.id)]);
    setMarked((n) => n - 1);
    setShown((n) => n + 1);
    setFlipped(false);
    setSuggested(null);
    setError(null);
    shownAt.current = performance.now();
  }, []);

  return {
    current,
    loading,
    flipped,
    suggested,
    busy,
    reviewed,
    marked,
    shown,
    remaining: cards.length + beyond,
    reviewsDue,
    error,
    flip,
    answer,
    rate,
    markKnown,
    putBack,
  };
}
