import { api } from "@/lib/api";

/** A dictionary entry (backend/app/api/vocab.py WordOut). */
export type Word = {
  id: number;
  word: string;
  phonetic: string | null;
  /** Chinese glosses, one part of speech per line. */
  translation: string;
  /** English definitions, one per line, when the dictionary has them. */
  definition: string | null;
};

export type CardSource = "book" | "auto" | "manual" | "placement";
export type CardStatus = "new" | "learning" | "known" | "suspended";

/** A word with the learner's card for it; card fields are null for a book word never met. */
export type Card = {
  word: Word;
  source: CardSource | null;
  status: CardStatus | null;
  due: string | null;
  last_review: string | null;
};

export type BookProgress = {
  id: string;
  name_zh: string;
  name_en: string;
  total: number;
  learning: number;
  known: number;
};

export type Today = {
  reviews_due: number;
  /** New words still to learn today (the rest of the limit, if that many are left). */
  new_left: number;
  new_limit: number;
  new_started: number;
};

export type VocabOverview = {
  books: BookProgress[];
  book_id: string | null;
  /** Null = the default, `daily_new_default`. */
  daily_new: number | null;
  daily_new_default: number;
  /** A screening batch was submitted for the current book. */
  screened: boolean;
  today: Today;
};

export type Queue = {
  reviews: Card[];
  new: Card[];
  /** All reviews due now; `reviews` holds at most 100 of them. */
  reviews_due: number;
  new_limit: number;
  new_started: number;
  book_id: string | null;
};

export type Rating = 1 | 2 | 3 | 4;

export type ScreenResult = { known: number; shown: number; skipped_ahead: boolean };

export type Added = { card: Card; matched: "exact" | "case" | "lemma"; added: boolean };

export const DAILY_NEW_MAX = 200;

/** The browser's time zone: "today" is the learner's day when their profile has none. */
export function browserTimeZone(): string | undefined {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || undefined;
  } catch {
    return undefined;
  }
}

function withTz(path: string, params: Record<string, string> = {}): string {
  const tz = browserTimeZone();
  const query = new URLSearchParams({ ...params, ...(tz ? { tz } : {}) }).toString();
  return query ? `${path}?${query}` : path;
}

export const fetchVocab = () => api<VocabOverview>(withTz("/vocab"));

export const chooseBook = (bookId: string, dailyNew: number | null) =>
  api<void>("/vocab/book", { method: "PUT", json: { book_id: bookId, daily_new: dailyNew } });

export const fetchQueue = (mode: "all" | "new" = "all") =>
  api<Queue>(withTz("/vocab/queue", { mode }));

export const rate = (wordId: number, rating: Rating, durationMs?: number) =>
  api<Card>("/vocab/reviews", {
    method: "POST",
    json: { word_id: wordId, rating, duration_ms: durationMs },
  });

export const fetchScreenBatch = () => api<{ words: Word[] }>("/vocab/screen");

export const submitScreen = (shown: number[], known: number[]) =>
  api<ScreenResult>("/vocab/screen", { method: "POST", json: { shown, known } });

export const suggestWords = (prefix: string) =>
  api<Word[]>(`/vocab/words?${new URLSearchParams({ q: prefix })}`);

export const fetchMine = (limit: number, offset: number) =>
  api<{ words: Card[]; total: number }>(`/vocab/mine?limit=${limit}&offset=${offset}`);

export const addMine = (word: string) =>
  api<Added>("/vocab/mine", { method: "POST", json: { word } });

export const removeMine = (wordId: number) =>
  api<void>(`/vocab/mine/${wordId}`, { method: "DELETE" });

/** Marking the current book's common words known from the placement test's vocabulary size. */
export type PlacementKnown = {
  /** Why nothing is offered; null when `count` words can be marked. */
  unavailable: "no_placement" | "unreliable" | "no_book" | null;
  book_id: string | null;
  up_to_rank: number | null;
  count: number;
  /** Words marked known this way so far (what undo takes back). */
  marked: number;
};

export const fetchPlacementKnown = () => api<PlacementKnown>("/vocab/placement-known");

export const markPlacementKnown = () =>
  api<{ count: number }>("/vocab/placement-known", { method: "POST" });

export const undoPlacementKnown = () =>
  api<{ count: number }>("/vocab/placement-known", { method: "DELETE" });

export const bookName = (book: { name_en: string; name_zh: string }, locale: string) =>
  locale.startsWith("zh") ? book.name_zh : book.name_en;

/** Share of the book met: being learned or known, 0–100. */
export function bookPercent(book: BookProgress): number {
  return book.total ? Math.floor(((book.learning + book.known) * 100) / book.total) : 0;
}
