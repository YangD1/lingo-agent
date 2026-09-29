"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { type Card, fetchQueue, type Rating, rate as rateCard } from "@/lib/vocab";

export type ReviewMode = "all" | "new";

export type ReviewSession = {
  /** Null while loading, and once there is nothing left. */
  current: Card | null;
  loading: boolean;
  /** The back of the card is showing; rating is possible only then. */
  flipped: boolean;
  /** A rating is being saved. */
  busy: boolean;
  /** Cards rated in this session. */
  reviewed: number;
  /** Cards still waiting, counting reviews beyond the page the server sent. */
  remaining: number;
  /** When done in `new` mode: reviews that are due. */
  reviewsDue: number;
  error: unknown;
  flip: () => void;
  rate: (rating: Rating) => Promise<void>;
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
  const [busy, setBusy] = useState(false);
  const [reviewed, setReviewed] = useState(0);
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

  const rate = useCallback(
    async (rating: Rating) => {
      if (!current || !flipped || busy) return;
      setBusy(true);
      setError(null);
      try {
        await rateCard(current.word.id, rating, Math.round(performance.now() - shownAt.current));
        setReviewed((n) => n + 1);
        setFlipped(false);
        const rest = cards.slice(1);
        if (rest.length) {
          setCards(rest);
          shownAt.current = performance.now();
        } else {
          setCards([]);
          setLoading(true);
          apply(await nextBatch(mode));
        }
      } catch (e) {
        setError(e);
        setLoading(false);
      } finally {
        setBusy(false);
      }
    },
    [current, flipped, busy, cards, mode, apply],
  );

  return {
    current,
    loading,
    flipped,
    busy,
    reviewed,
    remaining: cards.length + beyond,
    reviewsDue,
    error,
    flip,
    rate,
  };
}
