import { describe, expect, it } from "vitest";

import {
  chatUrl,
  type EditItem,
  isStale,
  layoutFor,
  MAX_PARAGRAPHS_PER_REQUEST,
  MAX_QUOTE_CHARS,
  nextToTranslate,
  offersWorkspace,
  PASTE_HINT_CHARS,
  pendingItems,
  quoteBlock,
  sentencesOf,
  withQuote,
  wordDiff,
  type WorkspaceEdit,
} from "./workspace";

describe("offersWorkspace", () => {
  it("offers the workspace from PASTE_HINT_CHARS characters, not counting the edges", () => {
    expect(offersWorkspace("a".repeat(PASTE_HINT_CHARS))).toBe(true);
    expect(offersWorkspace("a".repeat(PASTE_HINT_CHARS - 1))).toBe(false);
    expect(offersWorkspace(`  ${"a".repeat(PASTE_HINT_CHARS - 1)}\n\n`)).toBe(false);
  });
});

describe("quoteBlock", () => {
  it("puts the selection on one quoted line", () => {
    expect(quoteBlock("  The cat\n  sat on\tthe mat. ")).toBe("> The cat sat on the mat.");
  });

  it("cuts a long selection with an ellipsis", () => {
    const quote = quoteBlock("word ".repeat(400));
    expect(quote.length).toBeLessThanOrEqual(MAX_QUOTE_CHARS + 2);
    expect(quote.endsWith("…")).toBe(true);
  });

  it("is empty for blank text", () => {
    expect(quoteBlock(" \n ")).toBe("");
  });
});

describe("withQuote", () => {
  it("starts an empty box with the quote and a line to type on", () => {
    expect(withQuote("", "> Hi")).toBe("> Hi\n\n");
  });

  it("adds the quote after what was typed, as its own paragraph", () => {
    expect(withQuote("What about this?\n", "> Hi")).toBe("What about this?\n\n> Hi\n\n");
  });

  it("leaves the text alone without a quote", () => {
    expect(withQuote("Hello", "")).toBe("Hello");
  });
});

describe("chatUrl", () => {
  it("names the conversation and the open document", () => {
    expect(chatUrl("c1", "d1")).toBe("/chat?c=c1&w=d1");
    expect(chatUrl("c1", null)).toBe("/chat?c=c1");
  });

  it("has no document without a conversation", () => {
    expect(chatUrl(null, "d1")).toBe("/chat");
  });
});

describe("layoutFor", () => {
  it("splits on wide screens, covers the chat on medium ones and uses tabs on phones", () => {
    expect(layoutFor(true, true)).toBe("split");
    expect(layoutFor(false, true)).toBe("overlay");
    expect(layoutFor(false, false)).toBe("tabs");
  });
});

describe("sentencesOf", () => {
  it("cuts after a stop and the space after it, keeping every character", () => {
    const p = 'He left. "Why?" she asked! It cost 3.5 dollars… Then';
    const parts = sentencesOf(p);
    expect(parts).toEqual(["He left. ", '"Why?" ', "she asked! ", "It cost 3.5 dollars… ", "Then"]);
    expect(parts.join("")).toBe(p);
  });

  it("is the whole paragraph without a stop", () => {
    expect(sentencesOf("no stop here")).toEqual(["no stop here"]);
  });
});

describe("nextToTranslate", () => {
  it("takes what's in view and not done or on the way, in order, one request at a time", () => {
    expect(nextToTranslate([5, 1, 2, 1], new Set([2]), new Set([5]))).toEqual([1]);
    const many = Array.from({ length: 10 }, (_, i) => 9 - i);
    expect(nextToTranslate(many, new Set(), new Set())).toEqual([0, 1, 2, 3, 4, 5]);
    expect(MAX_PARAGRAPHS_PER_REQUEST).toBe(6);
  });
});

describe("wordDiff", () => {
  const show = (before: string, after: string) =>
    wordDiff(before, after)
      .map(({ text, op }) => (op === "same" ? text : op === "del" ? `[-${text}-]` : `{+${text}+}`))
      .join("");

  it("marks the words that go and come, the removed ones first", () => {
    expect(show("He go to school yesterday.", "He went to school yesterday.")).toBe(
      "He [-go-]{+went+} to school yesterday.",
    );
    expect(show("I am agree with you.", "I agree with you.")).toBe("I [-am -]agree with you.");
    expect(show("a big dog", "a big, friendly dog")).toBe("a big{+,+} {+friendly +}dog");
    expect(show("I has went home", "I have gone home")).toBe("I [-has went-]{+have gone+} home");
  });

  it("keeps contractions whole and puts the pieces back together", () => {
    const before = "I dont't know, it's fine.";
    const after = "I don't know; it's fine!";
    expect(show(before, after)).toBe("I [-dont't-]{+don't+} know[-,-]{+;+} it's fine[-.-]{+!+}");
    const pieces = wordDiff(before, after);
    expect(pieces.filter((p) => p.op !== "ins").map((p) => p.text).join("")).toBe(before);
    expect(pieces.filter((p) => p.op !== "del").map((p) => p.text).join("")).toBe(after);
  });

  it("handles an empty side", () => {
    expect(wordDiff("", "new")).toEqual([{ text: "new", op: "ins" }]);
    expect(wordDiff("old", "")).toEqual([{ text: "old", op: "del" }]);
  });
});

describe("isStale", () => {
  it("is stale unless the passage is in the text exactly once", () => {
    expect(isStale("go to", "I go to school.")).toBe(false);
    expect(isStale("go to", "I went to school.")).toBe(true);
    expect(isStale("to", "I go to school to learn.")).toBe(true);
  });
});

describe("pendingItems", () => {
  const item = (index: number, status: EditItem["status"]): EditItem => ({
    index,
    original: `o${index}`,
    replacement: `r${index}`,
    reason: "",
    status,
    stale: false,
  });
  const edit = (id: string, items: EditItem[]): WorkspaceEdit => ({
    id,
    doc_id: "d1",
    base_version: 1,
    created_at: "2026-10-15T00:00:00Z",
    items,
  });

  it("lists the undecided items, newest proposal first", () => {
    const edits = [edit("new", [item(0, "accepted"), item(1, "pending")]), edit("old", [item(0, "pending")])];
    expect(pendingItems(edits).map(({ edit, item }) => `${edit.id}:${item.index}`)).toEqual(["new:1", "old:0"]);
  });
});
