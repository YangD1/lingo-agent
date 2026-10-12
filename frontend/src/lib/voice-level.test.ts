import { afterEach, describe, expect, it } from "vitest";

import {
  browserMouth,
  LEVEL_GATE,
  levelFromRms,
  levelWatched,
  setLevelSource,
  voiceLevel,
  watchLevel,
} from "./voice-level";

describe("levelFromRms", () => {
  it("is silent up to the gate", () => {
    expect(levelFromRms(0)).toBe(0);
    expect(levelFromRms(LEVEL_GATE)).toBe(0);
    expect(levelFromRms(Number.NaN)).toBe(0);
  });

  it("rises on a log scale and tops out at 1", () => {
    const quiet = levelFromRms(0.04);
    const mid = levelFromRms(0.08);
    // Doubling the RMS adds the same amount wherever it is.
    expect(levelFromRms(0.16) - mid).toBeCloseTo(mid - quiet, 5);
    expect(quiet).toBeGreaterThan(0.2); // a quiet syllable still opens the mouth
    expect(levelFromRms(0.3)).toBeCloseTo(1);
    expect(levelFromRms(0.9)).toBe(1);
  });
});

describe("the level source", () => {
  afterEach(() => setLevelSource(() => 0)());

  it("is 0 with no source, then follows the one set, clamped to 0..1", () => {
    expect(voiceLevel(0)).toBe(0);
    setLevelSource(() => 1.7);
    expect(voiceLevel(0)).toBe(1);
  });

  it("stops a source only while it is still the current one", () => {
    const stopFirst = setLevelSource(() => 0.3);
    setLevelSource(() => 0.6);
    stopFirst(); // the call was replaced by a reading: it mustn't silence it
    expect(voiceLevel(0)).toBe(0.6);
  });
});

describe("watchLevel", () => {
  it("counts the avatars watching, each unmarking once", () => {
    expect(levelWatched()).toBe(false);
    const a = watchLevel();
    const b = watchLevel();
    a();
    a();
    expect(levelWatched()).toBe(true);
    b();
    expect(levelWatched()).toBe(false);
  });
});

describe("browserMouth", () => {
  it("opens on each word and closes after it", () => {
    const mouth = browserMouth(0);
    mouth.pulse(1000);
    const open = mouth.level(1000);
    expect(open).toBeGreaterThan(0.8);
    expect(mouth.level(1100)).toBeLessThan(open);
    expect(mouth.level(1600)).toBeLessThan(0.05);
  });

  it("flaps on its own when the voice sends no word events", () => {
    const mouth = browserMouth(0);
    const levels = Array.from({ length: 40 }, (_, i) => mouth.level(i * 25));
    expect(Math.max(...levels)).toBeGreaterThan(0.5);
    expect(Math.min(...levels)).toBeLessThan(0.1);
    expect(levels.every((x) => x >= 0 && x <= 1)).toBe(true);
  });
});
