"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { type CardAction, decideCard, fetchCards, type TutorCard } from "@/lib/cards";
import type { PlanChoice } from "@/lib/plan";

/** A conversation's cards by turn; a switch starts empty without an effect resetting it. */
type Owned = { conversationId: string | null; cards: TutorCard[] };

export type CardsView = {
  byTurn: Record<string, TutorCard[]>;
  /** Apply, decline or undo; the card shows the result. Rejects with the ApiError. */
  decide: (card: TutorCard, action: CardAction, choice?: PlanChoice) => Promise<void>;
};

function upsert(cards: TutorCard[], card: TutorCard): TutorCard[] {
  const at = cards.findIndex((c) => c.id === card.id);
  if (at < 0) return [...cards, card];
  // A streamed card has no live numbers; keep the ones the list brought.
  return cards.map((c, i) => (i === at ? { ...card, live: card.live ?? c.live } : c));
}

/**
 * The cards the tutor showed in a conversation (ADR 0015 §4): loaded with it, added as
 * they stream in, and reloaded after each turn for their current status and numbers.
 */
export function useCards(
  conversationId: string | null,
  onDecided?: (card: TutorCard) => void,
) {
  const [owned, setOwned] = useState<Owned>({ conversationId, cards: [] });
  const current = useRef(conversationId);
  useEffect(() => {
    current.current = conversationId;
  });
  const setCards = useCallback(
    (update: (cards: TutorCard[]) => TutorCard[]) =>
      setOwned((s) => {
        const mine = s.conversationId === current.current ? s.cards : [];
        return { conversationId: current.current, cards: update(mine) };
      }),
    [],
  );

  const reload = useCallback(() => {
    const id = current.current;
    if (id === null) return;
    fetchCards(id).then(
      (body) => current.current === id && setCards(() => body.cards),
      () => {},
    );
  }, [setCards]);

  useEffect(reload, [conversationId, reload]);

  /** A card streamed during the reply. */
  const add = useCallback((card: TutorCard) => setCards((all) => upsert(all, card)), [setCards]);

  const decide = useCallback(
    async (card: TutorCard, action: CardAction, choice?: PlanChoice) => {
      const updated = await decideCard(card.id, action, choice);
      setCards((all) => upsert(all, updated));
      onDecided?.(updated);
    },
    [setCards, onDecided],
  );

  const cards = owned.conversationId === conversationId ? owned.cards : [];
  const byTurn: Record<string, TutorCard[]> = {};
  for (const card of cards) (byTurn[card.turn_id] ??= []).push(card);
  return { byTurn, decide, add, reload };
}
