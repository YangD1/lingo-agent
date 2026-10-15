import { useSyncExternalStore } from "react";

import { api } from "./api";

/** The chat workspace's documents (ADR 0043): backend/app/api/workspace.py. */
export type WorkspaceKind = "reading" | "writing";

export type WorkspaceDoc = {
  id: string;
  conversation_id: string;
  kind: WorkspaceKind;
  title: string;
  /** paste / message / article / writing / blank */
  source: string;
  source_ref: string | null;
  created_by: "learner" | "tutor";
  version: number;
  /** A pasted text cut to the reading limit (Q83g). */
  truncated: boolean;
  created_at: string;
  updated_at: string;
};

export type WorkspaceVersion = {
  number: number;
  author: "learner" | "tutor";
  reverted_from: number | null;
  created_at: string;
  updated_at: string;
};

export type WorkspaceDocDetail = WorkspaceDoc & {
  /** reading: `{paragraphs}`; writing: `{text}`. */
  content: { paragraphs?: string[]; text?: string };
  words: number;
  versions: WorkspaceVersion[];
};

export const listDocs = (conversationId: string) =>
  api<WorkspaceDoc[]>(`/conversations/${conversationId}/workspace`);

export const getDoc = (docId: string) => api<WorkspaceDocDetail>(`/workspace/docs/${docId}`);

/** A document from text the learner pasted into the input box. */
export const createPasted = (conversationId: string, kind: WorkspaceKind, text: string) =>
  api<WorkspaceDocDetail>(`/conversations/${conversationId}/workspace`, {
    method: "POST",
    json: { kind, source: "paste", text },
  });

export const deleteDoc = (docId: string) =>
  api<void>(`/workspace/docs/${docId}`, { method: "DELETE" });

/** Pasting at least this much into the input box offers the workspace (ADR 0043 §4). */
export const PASTE_HINT_CHARS = 800;

export const offersWorkspace = (pasted: string) => pasted.trim().length >= PASTE_HINT_CHARS;

/** A selection quoted into the input box is cut to this many characters (ADR 0043 §4). */
export const MAX_QUOTE_CHARS = 600;

/** The selected text as a Markdown quote block: one line, cut to MAX_QUOTE_CHARS. */
export function quoteBlock(selected: string): string {
  const flat = selected.replace(/\s+/g, " ").trim();
  if (!flat) return "";
  const cut = flat.length > MAX_QUOTE_CHARS ? `${flat.slice(0, MAX_QUOTE_CHARS - 1).trimEnd()}…` : flat;
  return `> ${cut}`;
}

/** The input box's text with a quote added: on its own paragraph, then a line to type on. */
export function withQuote(text: string, quote: string): string {
  if (!quote) return text;
  const before = text.trimEnd();
  return `${before ? `${before}\n\n` : ""}${quote}\n\n`;
}

/** The chat page's address for a conversation and the document open beside it. */
export function chatUrl(conversationId: string | null, docId: string | null): string {
  if (!conversationId) return "/chat";
  const query = new URLSearchParams({ c: conversationId });
  if (docId) query.set("w", docId);
  return `/chat?${query}`;
}

/**
 * How the workspace sits next to the chat (ADR 0043 §2): side by side with a divider from
 * 1024px, over the chat column from 768px, and as a tab of its own on phones.
 */
export type WorkspaceLayout = "split" | "overlay" | "tabs";

const SPLIT_QUERY = "(min-width: 1024px)";
const OVERLAY_QUERY = "(min-width: 768px)";

export function layoutFor(split: boolean, overlay: boolean): WorkspaceLayout {
  return split ? "split" : overlay ? "overlay" : "tabs";
}

function currentLayout(): WorkspaceLayout {
  if (!window.matchMedia) return "split";
  return layoutFor(window.matchMedia(SPLIT_QUERY).matches, window.matchMedia(OVERLAY_QUERY).matches);
}

export function useWorkspaceLayout(): WorkspaceLayout {
  return useSyncExternalStore(
    (listener) => {
      const queries = [SPLIT_QUERY, OVERLAY_QUERY].map((q) => window.matchMedia?.(q));
      queries.forEach((q) => q?.addEventListener("change", listener));
      return () => queries.forEach((q) => q?.removeEventListener("change", listener));
    },
    currentLayout,
    () => "split",
  );
}

/** The reading view's three ways to show a document (ADR 0043 §4). */
export type ReadingDisplay = "original" | "both" | "translation";

/** Paragraphs translated in one request at most: backend/app/workspace/ai.py. */
export const MAX_PARAGRAPHS_PER_REQUEST = 6;

export type ParagraphTranslations = {
  version: number;
  translations: { index: number; text: string }[];
};

/** Paragraphs of the current version in Chinese: made once, then kept on the server. */
export const translateParagraphs = (docId: string, paragraphs: number[]) =>
  api<ParagraphTranslations>(`/workspace/docs/${docId}/translate`, {
    method: "POST",
    json: { paragraphs },
  });

export type SentenceAnalysis = {
  main: string;
  clauses: { text: string; role: string }[];
  phrases: { text: string; meaning: string }[];
  meaning: string;
  tip: string;
};

export const analyzeSentence = (docId: string, paragraph: number, sentence: string) =>
  api<SentenceAnalysis>(`/workspace/docs/${docId}/analyze`, {
    method: "POST",
    json: { paragraph, sentence },
  });

/**
 * The paragraphs to translate next: those in view without a translation or a request on
 * the way, in reading order, at most one request's worth. The rest wait for the next round.
 */
export function nextToTranslate(
  visible: Iterable<number>,
  done: ReadonlySet<number>,
  pending: ReadonlySet<number>,
): number[] {
  return [...new Set(visible)]
    .filter((i) => !done.has(i) && !pending.has(i))
    .sort((a, b) => a - b)
    .slice(0, MAX_PARAGRAPHS_PER_REQUEST);
}

/**
 * A paragraph cut into sentences, each with the space after it, so that they join back
 * into the paragraph. A stop ends a sentence only before a space ("3.5", "e.g.x" don't).
 */
export function sentencesOf(paragraph: string): string[] {
  const out: string[] = [];
  const end = /[.!?…]+["'”’)\]]*\s+/g;
  let last = 0;
  for (const match of paragraph.matchAll(end)) {
    const stop = match.index + match[0].length;
    out.push(paragraph.slice(last, stop));
    last = stop;
  }
  if (last < paragraph.length) out.push(paragraph.slice(last));
  return out;
}
