import { describe, expect, it } from "vitest";

import { markWord, parseDefinition, parseTranslation } from "./meanings";

describe("parseTranslation", () => {
  it("splits parts of speech and folds domain-only lines away", () => {
    const m = parseTranslation("prep. 为, 因为, 至于\nconj. 因为\n[计] DOS批处理命令:对一组参数重复执行指定的命令");
    expect(m.main).toEqual([
      { pos: "prep.", domain: null, text: "为，因为，至于" },
      { pos: "conj.", domain: null, text: "因为" },
    ]);
    expect(m.domain).toEqual([{ pos: null, domain: "计", text: "DOS批处理命令:对一组参数重复执行指定的命令" }]);
  });

  it("keeps lines without a part of speech and writes adjectives as adj.", () => {
    const m = parseTranslation("a. 熔化的, 融化的\nrun的过去式和过去分词\n[计] 运行");
    expect(m.main).toEqual([
      { pos: "adj.", domain: null, text: "熔化的，融化的" },
      { pos: null, domain: null, text: "run的过去式和过去分词" },
    ]);
    expect(m.domain).toHaveLength(1);
  });

  it("keeps a domain tag that follows a part of speech on the main sense", () => {
    expect(parseTranslation("n. [经] 广告（advertisement的复数）；宣传").main).toEqual([
      { pos: "n.", domain: "经", text: "广告（advertisement的复数）；宣传" },
    ]);
  });

  it("shows domain lines when they are all the word has", () => {
    const m = parseTranslation("[医] 库\n[法] 银行");
    expect(m.main.map((s) => s.domain)).toEqual(["医", "法"]);
    expect(m.domain).toEqual([]);
  });

  it("leaves commas in English text alone", () => {
    expect(parseTranslation("abbr.[军] Armored Artillery Howitzer, 装甲榴弹炮").main[0]).toEqual({
      pos: "abbr.",
      domain: "军",
      text: "Armored Artillery Howitzer, 装甲榴弹炮",
    });
  });
});

describe("parseDefinition", () => {
  it("joins hard-wrapped lines onto the sense they continue", () => {
    expect(
      parseDefinition("prep. In the most general sense, indicating that in consideration\nof, in view of.\nconj. Because."),
    ).toEqual([
      { pos: "prep.", domain: null, text: "In the most general sense, indicating that in consideration of, in view of." },
      { pos: "conj.", domain: null, text: "Because." },
    ]);
  });

  it("does not take a wrapped word ending in a full stop for a part of speech", () => {
    expect(parseDefinition("prep. which anything is done or takes\nplace.")).toEqual([
      { pos: "prep.", domain: null, text: "which anything is done or takes place." },
    ]);
  });

  it("handles WordNet satellite adjectives, a missing first part of speech and no definition", () => {
    expect(parseDefinition("s. marked by precise accordance with details")[0].pos).toBe("adj.");
    expect(parseDefinition("plain text\nmore")).toEqual([{ pos: null, domain: null, text: "plain text more" }]);
    expect(parseDefinition(null)).toEqual([]);
  });
});

describe("markWord", () => {
  const hits = (sentence: string, forms: string[]) =>
    markWord(sentence, forms)
      .filter((s) => s.hit)
      .map((s) => s.text);

  it("marks inflections as whole words, in any case", () => {
    expect(hits("Go home. She went there, good?", ["go", "went", "goes"])).toEqual(["Go", "went"]);
    expect(markWord("I went.", ["went"]).map((s) => s.text).join("")).toBe("I went.");
  });

  it("marks phrases and apostrophes, and leaves sentences without the word whole", () => {
    expect(hits("Look it up, then look up the word.", ["look up"])).toEqual(["look up"]);
    expect(hits("Don\u2019t go.", ["don't"])).toEqual(["Don\u2019t"]);
    expect(markWord("Nothing here.", ["go"])).toEqual([{ text: "Nothing here.", hit: false }]);
  });
});
