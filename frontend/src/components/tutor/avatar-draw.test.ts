import { describe, expect, it } from "vitest";

import { DEFAULT_FUR, FUR_SWATCHES, luminance, OUTFITS, paletteFor } from "./avatar-draw";

const rgb = (hex: string) => [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16)) as [number, number, number];

describe("paletteFor", () => {
  it("falls back to orange for no fur or a malformed one", () => {
    expect(paletteFor(null).fur).toBe(DEFAULT_FUR);
    expect(paletteFor("orange").fur).toBe(DEFAULT_FUR);
    expect(paletteFor("#ABCDEF").fur).toBe("#abcdef");
  });

  it("derives a darker shade and a lighter belly from the fur", () => {
    for (const fur of FUR_SWATCHES.filter((f) => f !== "#48484f")) {
      const p = paletteFor(fur);
      expect(luminance(rgb(p.shade))).toBeLessThan(luminance(rgb(p.fur)));
      expect(luminance(rgb(p.light))).toBeGreaterThan(luminance(rgb(p.fur)));
    }
  });

  it("gives a black cat yellow eyes, so they show", () => {
    expect(paletteFor("#48484f").eye).toBe("#f1cb78");
    expect(paletteFor(DEFAULT_FUR).eye).toBe("#4a3631");
  });

  it("gives a dark cat a grey belly and a light one cream", () => {
    expect(paletteFor("#48484f").light).toBe("#8e8e92");
    expect(paletteFor(DEFAULT_FUR).light).toBe("#fce4d2");
  });

  it("matches the backend's outfit ids", () => {
    expect(OUTFITS).toEqual(["cat", "classic", "casual", "sporty", "artsy"]);
  });
});
