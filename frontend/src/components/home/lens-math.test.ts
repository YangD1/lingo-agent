import { describe, expect, it } from "vitest";

import zhCN from "../../../messages/zh-CN.json";
import en from "../../../messages/en.json";
import {
  barrelMap,
  type Box,
  coverSide,
  hitBox,
  idleTarget,
  layoutWall,
  MISTAKES,
  PAN,
  panFor,
  ROTATION,
  startOnMistake,
  toHero,
  toLocal,
  WHEEL_X,
  WHEEL_Y,
  wheelStep,
  WORDS,
} from "@/components/home/lens-math";

describe("the wall's words", () => {
  it("each have a meaning in both languages", () => {
    for (const { slug } of [...WORDS, ...MISTAKES]) {
      expect(zhCN.landing.lens.words, slug).toHaveProperty(slug);
      expect(en.landing.lens.words, slug).toHaveProperty(slug);
    }
    expect(Object.keys(en.landing.lens.words)).toHaveLength(WORDS.length + MISTAKES.length);
  });

  it("are laid out the same on every load, mistakes and all", () => {
    const a = layoutWall(2000, 110);
    expect(layoutWall(2000, 110)).toEqual(a);
    const all = a.flatMap((row) => row.words);
    expect(all.some(({ word }) => word.ipa === null)).toBe(true);
    // a thin row is thin all the way along
    for (const row of a) expect(row.words.every(({ style }) => (style === "thin") === row.thin)).toBe(true);
  });

  it("fill rows enough to cover the square", () => {
    const rows = layoutWall(1000, 100);
    expect(rows.length * 100 * 0.9).toBeGreaterThanOrEqual(1000);
  });
});

describe("geometry", () => {
  const f = { w: 1440, h: 900, side: coverSide(1440, 900), px: 37, py: -21 };

  it("maps hero points onto the wall and back", () => {
    for (const [x, y] of [
      [0, 0],
      [720, 450],
      [1440, 900],
      [123, 777],
    ]) {
      const [lx, ly] = toLocal(f, x, y);
      const [hx, hy] = toHero(f, lx, ly);
      expect(hx).toBeCloseTo(x, 6);
      expect(hy).toBeCloseTo(y, 6);
    }
  });

  it("puts the hero's centre, unpanned, at the wall's centre", () => {
    expect(toLocal({ ...f, px: 0, py: 0 }, 720, 450)).toEqual([f.side / 2, f.side / 2]);
  });

  it("covers every corner of the hero even at the furthest pan and wheel", () => {
    const px = PAN * f.w + WHEEL_X * f.w;
    const py = PAN * f.h + WHEEL_Y * f.h;
    for (const [sx, sy] of [
      [1, 1],
      [-1, 1],
      [1, -1],
      [-1, -1],
    ]) {
      for (const [x, y] of [
        [0, 0],
        [f.w, 0],
        [0, f.h],
        [f.w, f.h],
      ]) {
        const [lx, ly] = toLocal({ ...f, px: sx * px, py: sy * py }, x, y);
        expect(lx).toBeGreaterThanOrEqual(0);
        expect(lx).toBeLessThanOrEqual(f.side);
        expect(ly).toBeGreaterThanOrEqual(0);
        expect(ly).toBeLessThanOrEqual(f.side);
      }
    }
  });

  it("finds the box under a point, edges included", () => {
    const boxes: Box[] = [
      { l: 0, t: 0, r: 10, b: 10 },
      { l: 20, t: 0, r: 30, b: 10 },
    ];
    expect(hitBox(boxes, 5, 5)).toBe(0);
    expect(hitBox(boxes, 30, 10)).toBe(1);
    expect(hitBox(boxes, 15, 5)).toBe(-1);
  });

  it("slides the wall against the pointer, plus the wheel offset", () => {
    const [cx, cy] = panFor(1000, 800, 500, 400, 0, 0);
    expect(cx).toBeCloseTo(0);
    expect(cy).toBeCloseTo(0);
    const [px, py] = panFor(1000, 800, 1000, 800, 10, -5);
    expect(px).toBeCloseTo(-PAN * 1000 + 10);
    expect(py).toBeCloseTo(-PAN * 800 - 5);
  });

  it("stops the wheel at the wall's edge and says so", () => {
    const edge = WHEEL_Y * 800;
    expect(wheelStep(0, 0, 0, 50, 1000, 800)).toEqual({ wx: 0, wy: -50, moved: true });
    expect(wheelStep(0, -edge + 10, 0, 50, 1000, 800)).toEqual({ wx: 0, wy: -edge, moved: true });
    expect(wheelStep(0, -edge, 0, 50, 1000, 800).moved).toBe(false);
    // and scrolling back up moves it again
    expect(wheelStep(0, -edge, 0, -50, 1000, 800).moved).toBe(true);
  });

  it("keeps the idle wander inside the hero", () => {
    for (let t = 0; t < 60; t += 0.7) {
      const [x, y] = idleTarget(1000, 800, t);
      expect(x).toBeGreaterThan(0);
      expect(x).toBeLessThan(1000);
      expect(y).toBeGreaterThan(0);
      expect(y).toBeLessThan(800);
    }
  });
});

describe("the barrel map", () => {
  it("leaves the centre alone and pushes outwards near the rim", () => {
    const n = 20;
    const map = barrelMap(n);
    const at = (i: number, j: number) => map.slice((j * n + i) * 4, (j * n + i) * 4 + 4);
    const [r, g, b, a] = at(10, 10);
    expect(Math.abs(r - 128)).toBeLessThanOrEqual(1);
    expect(Math.abs(g - 128)).toBeLessThanOrEqual(1);
    expect([b, a]).toEqual([128, 255]);
    expect(at(19, 10)[0]).toBeGreaterThan(200); // right edge samples further right
    expect(at(0, 10)[0]).toBeLessThan(56);
    expect(at(10, 0)[1]).toBeLessThan(56); // top edge samples further up
  });
});

describe("the starting point", () => {
  const f = { w: 1000, h: 800, side: coverSide(1000, 800) };
  // a box around the wall point that sits at hero (x, y) when the wall is unpanned
  const at = (x: number, y: number): Box => {
    const [lx, ly] = toLocal({ ...f, px: 0, py: 0 }, x, y);
    return { l: lx - 20, t: ly - 20, r: lx + 20, b: ly + 20 };
  };
  const underLens = (boxes: Box[], start: NonNullable<ReturnType<typeof startOnMistake>>) => {
    const [lx, ly] = toLocal({ ...f, px: start.px, py: start.py }, start.x, start.y);
    return hitBox(boxes, lx, ly);
  };

  it("scrolls the mistake needing the least scroll under the lens", () => {
    const boxes = [at(580, 320), at(100, 700), at(900, 100), at(560, 340)];
    const start = startOnMistake(f, boxes, (i) => i !== 0, 100);
    expect(start).not.toBeNull();
    expect(underLens(boxes, start!)).toBe(3);
    expect([start!.x, start!.y]).toEqual([580, 320]);
    // the pan drawn is the pointer parallax plus the wheel offset, as the frame loop draws it
    expect(start!.px).toBeCloseTo(panFor(f.w, f.h, start!.x, start!.y, start!.wx, start!.wy)[0]);
    expect(start!.py).toBeCloseTo(panFor(f.w, f.h, start!.x, start!.y, start!.wx, start!.wy)[1]);
  });

  it("reaches a mistake off screen within the wheel's range", () => {
    const boxes = [at(580 + WHEEL_X * 1000 * 0.9, 320)];
    const start = startOnMistake(f, boxes, () => true, 100);
    expect(underLens(boxes, start!)).toBe(0);
    expect(Math.abs(start!.wx)).toBeLessThanOrEqual(WHEEL_X * 1000);
  });

  it("moves the lens off its spot when the wheel can't bring the mistake all the way", () => {
    const boxes = [at(580, 320 - 600)];
    const start = startOnMistake(f, boxes, () => true, 100);
    expect(underLens(boxes, start!)).toBe(0);
    expect(start!.wy).toBeCloseTo(WHEEL_Y * 800);
    expect(start!.y).toBeLessThan(320);
    expect(start!.y).toBeGreaterThanOrEqual(100);
  });

  it("gives up when no mistake can be brought under a whole lens", () => {
    expect(startOnMistake(f, [at(580 + 3000, 320)], () => true, 100)).toBeNull();
    expect(startOnMistake(f, [at(580, 320)], () => false, 100)).toBeNull();
  });

  it("uses the shipped tilt by default", () => {
    expect(toLocal({ ...f, px: 0, py: 0 }, 0, 0)).toEqual(toLocal({ ...f, px: 0, py: 0, rotation: ROTATION }, 0, 0));
  });
});

describe("the starting point under reduced motion", () => {
  it("leaves out the parallax: the pan is the wheel offset alone", () => {
    const f = { w: 1000, h: 800, side: coverSide(1000, 800) };
    const [lx, ly] = toLocal({ ...f, px: 0, py: 0 }, 600, 350);
    const start = startOnMistake(f, [{ l: lx - 20, t: ly - 20, r: lx + 20, b: ly + 20 }], () => true, 100, true);
    expect(start!.px).toBeCloseTo(start!.wx);
    expect(start!.py).toBeCloseTo(start!.wy);
    expect(start!.wx).toBeCloseTo(-20);
    expect(start!.wy).toBeCloseTo(-30);
  });
});
