import { api } from "./api";
import { browserTimeZone } from "./vocab";

/** Pages a link card can lead to (backend/app/cards/tools.py LinkKind). */
export type LinkKind = "vocab_review" | "vocab_screen" | "placement" | "learner" | "word_books";

export const LINK_HREFS: Record<LinkKind, string> = {
  vocab_review: "/vocab/review",
  vocab_screen: "/vocab/screen",
  placement: "/placement",
  learner: "/learner",
  word_books: "/vocab",
};

/** proposed → applied | declined, applied → undone; cards without an effect are `info`. */
export type CardStatus = "proposed" | "applied" | "declined" | "undone" | "info";
export type CardAction = "apply" | "decline" | "undo";

type Named = { id: string; name_en: string; name_zh: string };

/** backend/app/api/cards.py CardOut; also the SSE `card` event (ADR 0015 §4). */
export type TutorCard = {
  id: string;
  /** The learner message of the turn the card was shown in. */
  turn_id: string;
  kind: "word_book" | "learning_goal" | "practice" | "link";
  /** word_book: book_id, daily_new; learning_goal: goal, target_exam, daily_minutes;
   * practice: kc_id; link: kind. */
  params: Record<string, unknown>;
  status: CardStatus;
  display: { book?: Named; kc?: Named & { cefr: string } };
  /** Link cards, from the list only: current numbers for the page. */
  live?: Record<string, unknown> | null;
  created_at: string | null;
  decided_at: string | null;
  undone_at: string | null;
};

export function fetchCards(conversationId: string): Promise<{ cards: TutorCard[] }> {
  const tz = browserTimeZone();
  const query = tz ? `?${new URLSearchParams({ tz })}` : "";
  return api<{ cards: TutorCard[] }>(`/conversations/${conversationId}/cards${query}`);
}

/** 409 card_not_pending / card_not_applied / setting_changed throw ApiError. */
export const decideCard = (cardId: string, action: CardAction) =>
  api<TutorCard>(`/cards/${encodeURIComponent(cardId)}/${action}`, { method: "POST" });
