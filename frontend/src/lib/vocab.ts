import { useEffect } from "react";

import { api } from "@/lib/api";
import { elapsedMs } from "@/lib/elapsed";

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
  /** Seconds until the next review for ratings 1–4, were the word rated now. */
  intervals: number[];
  /** Real example sentences, best first (ADR 0020); empty when no source has one. */
  sentences: SourcedExample[];
  /** The word and its inflections, lowercase, to pick it out of a sentence. */
  forms: string[];
  /** AI sentences already cached at the learner's level (task 44); shown without the button. */
  ai_examples: Example[];
  /** The learner's last assessed reading of this word was off (shadowing, Q56c). */
  mispronounced?: boolean;
  /** The word's first sense, short: the right answer on a listening card (task 63). */
  gloss: string;
  /** Wrong meanings for a listening card; only for words reviewed before (Q63b, Q63c). */
  choices: string[];
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

/**
 * Fired when the flashcards overlay closes after rating cards (ADR 0038): the page under it
 * stayed mounted, so whatever counts it shows (due, learned today, plan items) are stale.
 */
const REVIEWED_EVENT = "lingo:vocab-reviewed";

export function announceReviewed(): void {
  window.dispatchEvent(new Event(REVIEWED_EVENT));
}

/** Runs `reload` after a flashcards round over this page. */
export function useOnReviewed(reload: () => void): void {
  useEffect(() => {
    window.addEventListener(REVIEWED_EVENT, reload);
    return () => window.removeEventListener(REVIEWED_EVENT, reload);
  }, [reload]);
}

export const fetchVocab = () => api<VocabOverview>(withTz("/vocab"));

export const chooseBook = (bookId: string, dailyNew: number | null) =>
  api<void>("/vocab/book", { method: "PUT", json: { book_id: bookId, daily_new: dailyNew } });

export const fetchQueue = (mode: "all" | "new" = "all") =>
  api<Queue>(withTz("/vocab/queue", { mode }));

export const rate = (
  wordId: number,
  rating: Rating,
  durationMs?: number,
  format: ReviewFormat = "recognize",
) =>
  api<Card>("/vocab/reviews", {
    method: "POST",
    json: { word_id: wordId, rating, duration_ms: elapsedMs(durationMs), format },
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

/** A word looked up from a tutor message (backend LookupOut, ADR 0017 §2). */
export type Lookup = { word: Word; matched: "exact" | "case" | "lemma"; on_list: boolean };

export const lookupWord = (word: string) =>
  api<Lookup>(`/vocab/lookup?${new URLSearchParams({ word })}`);

export type Example = { en: string; zh: string };

/** An example sentence from a dictionary source; `url` is its page there, for attribution. */
export type SourcedExample = Example & { source: string; url: string | null };

/** AI example sentences at the learner's level, cached per word and level (ADR 0017 §3). */
export const fetchExamples = (wordId: number) =>
  api<{ sentences: Example[]; cefr: string }>(`/vocab/words/${wordId}/examples`, {
    method: "POST",
  });

export const removeMine = (wordId: number) =>
  api<void>(`/vocab/mine/${wordId}`, { method: "DELETE" });

/** Stops reviewing a word (task 120); idempotent. */
export const markKnown = (wordId: number) =>
  api<void>(`/vocab/cards/${wordId}/known`, { method: "POST" });

/** Reviews a known word again, from where it left off; idempotent. */
export const unmarkKnown = (wordId: number) =>
  api<void>(`/vocab/cards/${wordId}/known`, { method: "DELETE" });

export const fetchKnown = (q: string, limit: number, offset: number) =>
  api<{ words: Card[]; total: number }>(
    `/vocab/known?${new URLSearchParams({ q, limit: String(limit), offset: String(offset) })}`,
  );

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

const MINUTE = 60;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

/** "<1 min", "6 min", "3 hr", "4 days", "2 mths", "1.5 yrs": the next review, on a rating button. */
export function formatInterval(seconds: number, locale: string): string {
  const unit = (n: number, u: string, digits = 0) =>
    new Intl.NumberFormat(locale, {
      style: "unit",
      unit: u,
      unitDisplay: "short",
      maximumFractionDigits: digits,
    }).format(n);
  if (seconds < MINUTE) return `<${unit(1, "minute")}`;
  if (seconds < HOUR) return unit(Math.round(seconds / MINUTE), "minute");
  if (seconds < DAY) return unit(Math.round(seconds / HOUR), "hour");
  if (seconds < 30 * DAY) return unit(Math.round(seconds / DAY), "day");
  if (seconds < 365 * DAY) return unit(Math.round(seconds / (30 * DAY)), "month");
  return unit(seconds / (365 * DAY), "year", 1);
}

/**
 * How a card is shown (task 63): the word (recall its meaning), its sound (pick the
 * meaning of four), or its sound and meaning (type the word).
 */
export type ReviewFormat = "recognize" | "listen" | "spell";
/** What the learner picked on the review page; "mixed" draws one per card (Q63a). */
export type ReviewChoice = ReviewFormat | "mixed";
export const REVIEW_CHOICES: readonly ReviewChoice[] = ["recognize", "listen", "spell", "mixed"];

/**
 * The format `card` is shown in. Words never reviewed are always recognised first (Q63b);
 * without anything to read aloud with there is no listening or spelling (P3 plan §7); a
 * listening card needs three wrong meanings. `seed` draws the format in "mixed".
 */
export function cardFormat(
  card: Card,
  choice: ReviewChoice,
  canSpeak: boolean,
  seed: number,
): ReviewFormat {
  if (choice === "recognize" || !canSpeak || card.last_review === null) return "recognize";
  const listenable = card.choices.length >= 3;
  if (choice === "mixed") {
    const formats: ReviewFormat[] = listenable
      ? ["recognize", "listen", "spell"]
      : ["recognize", "spell"];
    return formats[seed % formats.length] ?? "recognize";
  }
  return choice === "listen" && !listenable ? "recognize" : choice;
}

/** The four meanings of a listening card, the right one among them, in an order set by `seed`. */
export function listenOptions(card: Card, seed: number): string[] {
  const options = [card.gloss, ...card.choices.slice(0, 3)];
  // A small seeded generator (mulberry32), so the order stays put while the card is shown.
  let state = seed >>> 0;
  const next = () => {
    state = (state + 0x6d2b79f5) >>> 0;
    let t = state;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
  for (let i = options.length - 1; i > 0; i--) {
    const j = Math.floor(next() * (i + 1));
    [options[i], options[j]] = [options[j] as string, options[i] as string];
  }
  return options;
}

/** Right, one letter off, or wrong (Q63d). */
export type SpellResult = "right" | "close" | "wrong";

/** The rating offered after an answer; the learner can pick another (Q63d). */
export const SUGGESTED_RATING: Record<SpellResult, Rating> = { right: 3, close: 2, wrong: 1 };

/** Case and outer spaces don't count, nor several spaces in a phrase (Q63e). */
export const normalizeSpelling = (text: string) => text.trim().replace(/\s+/g, " ").toLowerCase();

/** Edit distance table between `a` and `b` (insert, delete, replace one letter). */
function distances(a: string, b: string): number[][] {
  const d = Array.from({ length: a.length + 1 }, (_, i) =>
    Array.from({ length: b.length + 1 }, (_, j) => (i === 0 ? j : j === 0 ? i : 0)),
  );
  for (let i = 1; i <= a.length; i++) {
    for (let j = 1; j <= b.length; j++) {
      const row = d[i] as number[];
      const above = d[i - 1] as number[];
      row[j] = Math.min(
        (above[j] as number) + 1,
        (row[j - 1] as number) + 1,
        (above[j - 1] as number) + (a[i - 1] === b[j - 1] ? 0 : 1),
      );
    }
  }
  return d;
}

/** Judges what the learner typed against `word`; inflected forms are wrong (Q63e). */
export function judgeSpelling(typed: string, word: string): SpellResult {
  const a = normalizeSpelling(typed);
  const b = normalizeSpelling(word);
  if (!a) return "wrong";
  const distance = distances(a, b)[a.length]?.[b.length] ?? Infinity;
  return distance === 0 ? "right" : distance === 1 ? "close" : "wrong";
}

/**
 * The letters of `word` with whether the learner got each: a letter is missed when what
 * they typed has another letter there, or none.
 */
export function spellingMarks(typed: string, word: string): { char: string; ok: boolean }[] {
  const a = normalizeSpelling(typed);
  const b = word.trim().replace(/\s+/g, " ");
  const lower = b.toLowerCase();
  const d = distances(a, lower);
  const ok = new Array<boolean>(b.length).fill(false);
  let i = a.length;
  let j = b.length;
  // Walk back along a shortest edit path; a letter kept unchanged is one they got.
  while (i > 0 && j > 0) {
    const here = d[i]?.[j] as number;
    const same = a[i - 1] === lower[j - 1];
    if (here === (d[i - 1]?.[j - 1] as number) + (same ? 0 : 1)) {
      ok[j - 1] = same;
      i--;
      j--;
    } else if (here === (d[i - 1]?.[j] as number) + 1) {
      i--;
    } else {
      j--;
    }
  }
  return [...b].map((char, k) => ({ char, ok: ok[k] ?? false }));
}
