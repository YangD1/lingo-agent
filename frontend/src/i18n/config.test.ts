import { describe, expect, it } from "vitest";

import { negotiateLocale, resolveLocale } from "./config";

describe("negotiateLocale", () => {
  it.each([
    ["zh-CN,zh;q=0.9,en;q=0.8", "zh-CN"],
    ["zh-TW", "zh-CN"],
    ["en-US,en;q=0.9", "en"],
    ["fr-FR,zh;q=0.5,en;q=0.7", "en"],
    ["fr-FR,de;q=0.9", "en"],
    ["en;q=0,zh", "zh-CN"],
    ["ZH-hans", "zh-CN"],
    ["en;q=0.5,zh;q=0.5", "en"],
  ])("%s -> %s", (header, expected) => {
    expect(negotiateLocale(header)).toBe(expected);
  });

  it("defaults to English without a header", () => {
    expect(negotiateLocale(null)).toBe("en");
    expect(negotiateLocale("")).toBe("en");
  });
});

describe("resolveLocale", () => {
  it("prefers an explicit choice over the browser's languages", () => {
    expect(resolveLocale("en", "zh-CN")).toBe("en");
  });

  it("ignores unsupported cookie values", () => {
    expect(resolveLocale("fr", "zh-CN")).toBe("zh-CN");
  });
});
