import { describe, expect, it } from "vitest";

import { splitTokens } from "@/components/home/demo-player";

describe("splitTokens", () => {
  it("streams English a word at a time, keeping the trailing space with the word", () => {
    expect(splitTokens("I went hiking.")).toEqual(["I ", "went ", "hiking."]);
  });

  it("streams Chinese a character at a time, punctuation included", () => {
    expect(splitTokens("你好，世界")).toEqual(["你", "好", "，", "世", "界"]);
  });

  it("splits mixed text at the script boundary and loses nothing", () => {
    const text = "make 是让人不得不做：My boss made me stay late.";
    const pieces = splitTokens(text);
    expect(pieces.join("")).toBe(text);
    expect(pieces.slice(0, 3)).toEqual(["make ", "是", "让"]);
  });
});
