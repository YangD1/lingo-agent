import { describe, expect, it } from "vitest";

import en from "../../messages/en.json";
import zhCN from "../../messages/zh-CN.json";

type Tree = { [key: string]: string | Tree };

function flatten(tree: Tree, prefix = ""): Map<string, string> {
  const out = new Map<string, string>();
  for (const [key, value] of Object.entries(tree)) {
    const path = prefix ? `${prefix}.${key}` : key;
    if (typeof value === "string") out.set(path, value);
    else for (const [k, v] of flatten(value, path)) out.set(k, v);
  }
  return out;
}

const placeholders = (text: string) => [...text.matchAll(/\{(\w+)/g)].map((m) => m[1]).sort();

describe("message catalogs", () => {
  const catalogs = { en: flatten(en), "zh-CN": flatten(zhCN) };

  it("have exactly the same keys", () => {
    expect([...catalogs["zh-CN"].keys()].sort()).toEqual([...catalogs.en.keys()].sort());
  });

  it("use the same ICU placeholders for every key", () => {
    for (const [key, text] of catalogs.en) {
      expect(placeholders(catalogs["zh-CN"].get(key) ?? ""), key).toEqual(placeholders(text));
    }
  });

  it("have no empty strings", () => {
    for (const [locale, catalog] of Object.entries(catalogs)) {
      for (const [key, text] of catalog) expect(text.trim(), `${locale}:${key}`).not.toBe("");
    }
  });
});
