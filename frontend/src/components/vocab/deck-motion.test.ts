import { afterEach, describe, expect, it, vi } from "vitest";

import { comeBack, flyOff, rise, settle, turnAway, turnBack } from "./deck-motion";

type Frames = Keyframe[];

/** A card element that records what it was asked to animate. */
function card() {
  const played: Frames[] = [];
  const el = document.createElement("div");
  el.animate = ((frames: Frames) => {
    played.push(frames);
    return { finished: Promise.resolve(), cancel() {} } as unknown as Animation;
  }) as HTMLElement["animate"];
  el.getAnimations = () => [];
  return { el, played };
}

function reduceMotion(on: boolean) {
  vi.stubGlobal("matchMedia", (query: string) => ({ matches: on && query.includes("reduce") }));
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("deck motion", () => {
  it("turns, flies and rises with transforms", async () => {
    reduceMotion(false);
    const { el, played } = card();
    await turnAway(el);
    turnBack(el);
    flyOff(el, -1);
    rise(el);
    settle(el);
    expect(played).toHaveLength(5);
    for (const frames of played) expect(frames.some((f) => f.transform)).toBe(true);
    expect(played[2]!.at(-1)!.transform).toContain("translateX(-125%)");
  });

  it("only fades when motion is reduced", async () => {
    reduceMotion(true);
    const { el, played } = card();
    await turnAway(el);
    turnBack(el);
    flyOff(el, 1);
    rise(el);
    settle(el);
    comeBack(el);
    expect(played).toHaveLength(6);
    for (const frames of played) {
      expect(frames.every((f) => f.transform === undefined)).toBe(true);
      expect(frames.some((f) => f.opacity !== undefined)).toBe(true);
    }
  });

  it("sends a swiped card back from where the finger left it", () => {
    reduceMotion(false);
    const { el, played } = card();
    el.style.transform = "translateX(-40px) rotate(-2deg)";
    comeBack(el);
    expect(el.style.transform).toBe("");
    expect(played[0]![0]!.transform).toBe("translateX(-40px) rotate(-2deg)");
  });

  it("snaps back without the animation API", () => {
    const el = document.createElement("div");
    el.style.transform = "translateX(30px)";
    Object.defineProperty(el, "animate", { value: undefined });
    comeBack(el);
    expect(el.style.transform).toBe("");
  });
});
