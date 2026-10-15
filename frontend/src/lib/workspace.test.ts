import { describe, expect, it } from "vitest";

import {
  chatUrl,
  layoutFor,
  MAX_PARAGRAPHS_PER_REQUEST,
  MAX_QUOTE_CHARS,
  nextToTranslate,
  offersWorkspace,
  PASTE_HINT_CHARS,
  quoteBlock,
  sentencesOf,
  withQuote,
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
