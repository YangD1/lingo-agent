import { describe, expect, it } from "vitest";

import { DEFAULT_FUR, FUR_SWATCHES, luminance, OUTFITS, paletteFor } from "./avatar-draw";

const rgb = (hex: string) => [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16)) as [number, number, number];

describe("paletteFor", () => {
  it("falls back to the logo orange for no fur or a malformed one", () => {
    expect(paletteFor(null).fur).toBe(DEFAULT_FUR);
    expect(paletteFor("orange").fur).toBe(DEFAULT_FUR);
    expect(paletteFor("#ABCDEF").fur).toBe("#abcdef");
  });

  it("derives a darker shade and a lighter belly from the fur", () => {
    for (const fur of FUR_SWATCHES.filter((f) => f !== "#2e2b2b")) {
      const p = paletteFor(fur);
      expect(luminance(rgb(p.shade))).toBeLessThan(luminance(rgb(p.fur)));
      expect(luminance(rgb(p.light))).toBeGreaterThan(luminance(rgb(p.fur)));
    }
  });

  it("gives a black cat yellow eyes, so they show", () => {
    expect(paletteFor("#2e2b2b").eye).toBe("#f2c94c");
    expect(paletteFor(DEFAULT_FUR).eye).toBe("#2b2321");
  });

  it("outlines only a pale fur", () => {
    expect(paletteFor("#f4f1ec").edge).not.toBeNull();
    expect(paletteFor(DEFAULT_FUR).edge).toBeNull();
  });

  it("matches the backend's outfit ids", () => {
    expect(OUTFITS).toEqual(["cat", "classic", "casual", "sporty", "artsy"]);
  });
});
