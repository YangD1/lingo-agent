import { api } from "@/lib/api";

/** backend/app/api/reading.py (ADR 0024). */
export type Feed = {
  id: string;
  title: string;
  url: string;
  site_url: string | null;
  builtin: boolean;
  license: string;
  subscribed: boolean;
  /** Own feeds only: whoever added it, or an admin. */
  can_delete: boolean;
  last_fetched_at: string | null;
  /** Error code of the last failed fetch, until one succeeds. */
  last_error: string | null;
};

export type Feeds = { feeds: Feed[]; max_own: number };

export type ArticleBrief = {
  id: number;
  feed_id: string;
  feed_title: string;
  title: string;
  url: string;
  author: string | null;
  published_at: string;
  word_count: number;
  /** Only a teaser: read it at the source, never rewritten. */
  summary_only: boolean;
  license: string;
  tags: string[];
};

export type ArticleItem = ArticleBrief & {
  /** A version at my level is ready: opening it calls no model (Q43f). */
  rewritten: boolean;
  read: boolean;
};

export type ArticlePage = { articles: ArticleItem[]; next_cursor: string | null };

export const PAGE_SIZE = 30;

export function fetchArticles({ feedId, before }: { feedId?: string | null; before?: string | null } = {}) {
  const params = new URLSearchParams({ limit: String(PAGE_SIZE) });
  if (feedId) params.set("feed_id", feedId);
  if (before) params.set("before", before);
  return api<ArticlePage>(`/reading/articles?${params}`);
}

export const fetchFeeds = () => api<Feeds>("/reading/feeds");

export const addFeed = (url: string) => api<Feeds>("/reading/feeds", { method: "POST", json: { url } });

export const setSubscribed = (feedId: string, subscribed: boolean) =>
  api<Feeds>(`/reading/feeds/${feedId}/subscription`, { method: "PUT", json: { subscribed } });

export const deleteFeed = (feedId: string) => api<void>(`/reading/feeds/${feedId}`, { method: "DELETE" });

/** Feeds a learner added themselves count against `max_own`. */
export function ownCount(feeds: Feed[]): number {
  return feeds.filter((f) => !f.builtin && f.subscribed).length;
}

export type Article = ArticleBrief & {
  /** Paragraphs separated by blank lines, no markup. */
  body: string;
  site_url: string | null;
};

export type GlossaryWord = { word: string; word_id: number; form: string };
export type Question = { question: string; options: string[] };

/** While generating: rewriting, reviewing (the critic), fixing (rejected questions). */
export type VersionStage = "rewriting" | "reviewing" | "fixing";

export type Version = {
  id: string;
  article: ArticleBrief;
  level: string;
  status: "generating" | "ready" | "failed";
  stage: VersionStage | null;
  error_code: string | null;
  title: string | null;
  paragraphs: string[];
  word_count: number;
  glossary: GlossaryWord[];
  /** Without answers: those come back once answered. */
  questions: Question[];
};

export type QuizResult = { choice: number; correct: boolean; answer: number; evidence: string };

/** Why the original is shown instead of a version (Q43e). */
export type OriginalReason = "summary_only" | "not_rewritable" | "level_above";

export type ReadingSession = {
  id: string;
  article: Article;
  level: string;
  version: Version | null;
  original_reason: OriginalReason | null;
  results: QuizResult[] | null;
  finished_at: string | null;
};

export type Answered = { results: QuizResult[]; counted: boolean };

export const openReading = (articleId: number) =>
  api<ReadingSession>(`/reading/articles/${articleId}/session`, { method: "POST" });

export const fetchVersion = (versionId: string) => api<Version>(`/reading/versions/${versionId}`);

export const answerQuestions = (sessionId: string, choices: number[]) =>
  api<Answered>(`/reading/sessions/${sessionId}/answers`, { method: "POST", json: { choices } });

export const fetchDueWords = (sessionId: string, original: boolean) =>
  api<{ due: { word_id: number; form: string }[] }>(
    `/reading/sessions/${sessionId}/marks${original ? "?original=true" : ""}`,
  );

/** One English word, as the backend's glossary splits text (services/reading/glossary.py). */
export const WORD = /[A-Za-z]+(?:['’-][A-Za-z]+)*/g;

/** A word as the backend lists its forms: lowercase, straight apostrophe. */
export const formOf = (word: string) => word.replace(/’/g, "'").toLowerCase();

export type Piece = { text: string; word: boolean };

/** A paragraph cut into words and what is between them. */
export function pieces(paragraph: string): Piece[] {
  const out: Piece[] = [];
  let last = 0;
  for (const match of paragraph.matchAll(WORD)) {
    if (match.index > last) out.push({ text: paragraph.slice(last, match.index), word: false });
    out.push({ text: match[0], word: true });
    last = match.index + match[0].length;
  }
  if (last < paragraph.length) out.push({ text: paragraph.slice(last), word: false });
  return out;
}

export const paragraphsOf = (body: string) => body.split("\n\n").filter((p) => p.trim());
