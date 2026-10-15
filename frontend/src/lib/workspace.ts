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

/** Where a document opened from a page comes from (ADR 0043 §3–4). */
export type DocSource =
  | { source: "article"; id: number }
  | { source: "writing"; id: number };

/** An article (at the learner's level) or a submitted text, as a document. */
export const createFrom = (conversationId: string, from: DocSource) =>
  api<WorkspaceDocDetail>(`/conversations/${conversationId}/workspace`, {
    method: "POST",
    json:
      from.source === "article"
        ? { kind: "reading", source: "article", article_id: from.id }
        : { kind: "writing", source: "writing", writing_id: from.id },
  });

/** The conversation's document already made from that source, opened again instead of a copy. */
export const docFrom = (docs: WorkspaceDoc[], from: DocSource) =>
  docs.findLast((d) => d.source === from.source && d.source_ref === String(from.id));

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

// A reading document's paragraphs are Markdown blocks (task 84; how the backend cuts them:
// backend/app/workspace/markdown.py).

/** A fenced code block: shown as it is, never translated or analysed (Q84c). */
export const isCodeBlock = (block: string) => /^\s{0,3}(`{3,}|~{3,})/.test(block);

/** A table: translated whole, shown as a table, not cut into sentences. */
export const isTableBlock = (block: string) => block.split("\n").every((line) => /^\s*\|/.test(line));

const INLINE: [RegExp, string][] = [
  [/!\[([^\]]*)\]\([^)]*\)/g, "$1"],
  [/\[([^\]]+)\]\([^)]*\)/g, "$1"],
  [/`([^`]*)`/g, "$1"],
  [/(\*\*|__)(.+?)\1/g, "$2"],
  [/(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])/g, "$1"],
  [/(?<![\w_])_(?!\s)(.+?)(?<!\s)_(?![\w_])/g, "$1"],
  [/~~(.+?)~~/g, "$1"],
];

/** One line's words without its inline marks (bold, links, code…). */
export function plainOf(line: string): string {
  return INLINE.reduce((text, [pattern, keep]) => text.replace(pattern, keep), line)
    .replace(/\s+/g, " ")
    .trim();
}

/**
 * What a block is made of when it is cut into sentences (Q84b): headings, list items and
 * quotes keep their place; their inline marks are dropped. `marker` is a list item's
 * number ("2.") or bullet.
 */
export type Unit = {
  kind: "heading" | "item" | "quote" | "text";
  level: number;
  marker?: string;
  text: string;
};

export function unitsOf(block: string): Unit[] {
  const units: Unit[] = [];
  for (const line of block.split("\n")) {
    if (!line.trim()) continue;
    const heading = /^\s{0,3}(#{1,6})\s+(.*)$/.exec(line);
    const item = /^(\s*)([-*+]|\d{1,9}[.)])\s+(.*)$/.exec(line);
    const quote = /^\s{0,3}>\s?(.*)$/.exec(line);
    const last = units.at(-1);
    if (heading) units.push({ kind: "heading", level: heading[1].length, text: plainOf(heading[2]) });
    else if (item)
      units.push({
        kind: "item",
        level: Math.floor(item[1].length / 2),
        marker: /\d/.test(item[2]) ? item[2].replace(")", ".") : "•",
        text: plainOf(item[3]),
      });
    else if (quote && last?.kind === "quote") last.text = `${last.text} ${plainOf(quote[1])}`.trim();
    else if (quote) units.push({ kind: "quote", level: 0, text: plainOf(quote[1]) });
    // A line that only goes on: part of the item, quote or text before it.
    else if (last && last.kind !== "heading") last.text = `${last.text} ${plainOf(line)}`.trim();
    else units.push({ kind: "text", level: 0, text: plainOf(line) });
  }
  return units.filter((unit) => unit.text);
}

/** A block's words without its marks: what shadowing reads. */
export const plainBlock = (block: string) =>
  isCodeBlock(block) ? "" : unitsOf(block).map((unit) => unit.text).join(" ");

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

/** The learner's edit of the current version: 409 `workspace_version_conflict` if stale. */
export const saveText = (docId: string, baseVersion: number, text: string) =>
  api<WorkspaceDocDetail>(`/workspace/docs/${docId}/content`, {
    method: "PUT",
    json: { base_version: baseVersion, text },
  });

/** An earlier version's content, to look at before going back to it. */
export const getVersion = (docId: string, number: number) =>
  api<WorkspaceVersion & { content: WorkspaceDocDetail["content"] }>(
    `/workspace/docs/${docId}/versions/${number}`,
  );

/** Back to an earlier version, saved as a new one (no version is lost). */
export const revertTo = (docId: string, version: number) =>
  api<WorkspaceDocDetail>(`/workspace/docs/${docId}/revert`, { method: "POST", json: { version } });

export type EditItemStatus = "pending" | "accepted" | "declined";

export type EditItem = {
  index: number;
  original: string;
  replacement: string;
  reason: string;
  status: EditItemStatus;
  /** Pending, but the passage is no longer in the text exactly once. */
  stale: boolean;
};

/** One `propose_edit` of the tutor's: backend/app/workspace/edits.py. */
export type WorkspaceEdit = {
  id: string;
  doc_id: string;
  base_version: number;
  created_at: string;
  items: EditItem[];
};

/** The tutor's proposals for a document, newest first. */
export const listEdits = (docId: string) => api<WorkspaceEdit[]>(`/workspace/docs/${docId}/edits`);

/** Accept or decline items; the accepted ones make one new version. */
export const decideEdit = (editId: string, accept: number[], decline: number[]) =>
  api<{ doc: WorkspaceDocDetail; edit: WorkspaceEdit }>(`/workspace/edits/${editId}/decide`, {
    method: "POST",
    json: { accept, decline },
  });

/**
 * Whether a proposed change can no longer be accepted: its passage isn't in the text
 * exactly once (the learner rewrote it). Mirrors `edits.stale` on the server, but on the
 * text being typed, so the mark shows before it is saved.
 */
export function isStale(original: string, text: string): boolean {
  const start = text.indexOf(original);
  return start < 0 || text.indexOf(original, start + 1) >= 0;
}

/** The items still waiting for the learner, newest proposal first. */
export function pendingItems(edits: WorkspaceEdit[]): { edit: WorkspaceEdit; item: EditItem }[] {
  return edits.flatMap((edit) =>
    edit.items.filter((item) => item.status === "pending").map((item) => ({ edit, item })),
  );
}

export type DiffPiece = { text: string; op: "same" | "del" | "ins" };

// Words (with inner apostrophes), runs of spaces, and single other characters.
const TOKEN = /[\p{L}\p{N}]+(?:['’][\p{L}\p{N}]+)*|\s+|[^\p{L}\p{N}\s]/gu;

/**
 * A passage and its replacement word by word: what stays, what goes, what comes in.
 * Passages are a sentence or two, so a plain longest-common-subsequence table is enough.
 */
export function wordDiff(before: string, after: string): DiffPiece[] {
  const a = before.match(TOKEN) ?? [];
  const b = after.match(TOKEN) ?? [];
  // common[i][j]: the longest common run of a[i:] and b[j:].
  const common = Array.from({ length: a.length + 1 }, () => new Array<number>(b.length + 1).fill(0));
  for (let i = a.length - 1; i >= 0; i--) {
    for (let j = b.length - 1; j >= 0; j--) {
      common[i][j] = a[i] === b[j] ? common[i + 1][j + 1] + 1 : Math.max(common[i + 1][j], common[i][j + 1]);
    }
  }
  const out: DiffPiece[] = [];
  const push = (text: string, op: DiffPiece["op"]) => {
    const last = out.at(-1);
    if (last?.op === op) last.text += text;
    else out.push({ text, op });
  };
  let i = 0;
  let j = 0;
  while (i < a.length || j < b.length) {
    if (i < a.length && j < b.length && a[i] === b[j]) {
      push(a[i++], "same");
      j++;
    } else if (i < a.length && (j === b.length || common[i + 1][j] >= common[i][j + 1])) {
      push(a[i++], "del");
    } else {
      push(b[j++], "ins");
    }
  }
  // A replacement reads better whole: "[-has went-]{+have gone+}", not split at the space
  // between its words. A lone space between changes joins them when they both remove
  // and add; a pure insertion keeps its spaces, so either side still reads back.
  const merged: DiffPiece[] = [];
  const space = (k: number) =>
    /^\s+$/.test(out[k].text) && out[k - 1]?.op !== "same" && out[k + 1] !== undefined && out[k + 1].op !== "same";
  for (let k = 0; k < out.length; ) {
    if (out[k].op === "same") {
      merged.push(out[k++]);
      continue;
    }
    let end = k;
    while (end < out.length && (out[end].op !== "same" || space(end))) end++;
    const run = out.slice(k, end);
    if (run.some((p) => p.op === "del") && run.some((p) => p.op === "ins")) {
      const text = (skip: DiffPiece["op"]) => run.filter((p) => p.op !== skip).map((p) => p.text).join("");
      merged.push({ text: text("ins"), op: "del" }, { text: text("del"), op: "ins" });
    } else {
      merged.push(...run);
    }
    k = end;
  }
  return merged;
}
