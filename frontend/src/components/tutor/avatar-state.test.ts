import { describe, expect, it } from "vitest";

import {
  blinkAt,
  BLINK_MAX_MS,
  BLINK_MIN_MS,
  BLINK_MS,
  createAnimator,
  followMouth,
  JOY_MS,
  REST_POSE,
  stillPose,
  type AvatarState,
} from "./avatar-state";

/** Steps a fresh animator every 16ms from 0 to `until`, returning each pose. */
function run(
  until: number,
  state: AvatarState | ((t: number) => AvatarState),
  level: (t: number) => number = () => 0,
  random = () => 0.5,
) {
  const animator = createAnimator(random);
  const poses = [];
  for (let t = 0; t <= until; t += 16) {
    poses.push({ t, ...animator.step(t, typeof state === "function" ? state(t) : state, level(t)) });
  }
  return poses;
}

describe("blinks", () => {
  it("shut and reopen within a blink", () => {
    expect(blinkAt(-1)).toBe(0);
    expect(blinkAt(BLINK_MS / 2)).toBeCloseTo(1);
    expect(blinkAt(BLINK_MS)).toBe(0);
  });

  it("come every 3–6 s, spaced by the random source", () => {
    for (const random of [() => 0, () => 0.999]) {
      const shut = run(20000, "idle", () => 0, random).filter((p) => p.eyes < 0.3).map((p) => p.t);
      const starts = shut.filter((t, i) => i === 0 || t - shut[i - 1] > BLINK_MS);
      expect(starts.length).toBeGreaterThan(2);
      for (let i = 1; i < starts.length; i++) {
        const gap = starts[i] - starts[i - 1];
        expect(gap).toBeGreaterThanOrEqual(BLINK_MIN_MS);
        expect(gap).toBeLessThanOrEqual(BLINK_MAX_MS + BLINK_MS + 32);
      }
    }
  });
});

describe("states", () => {
  it("listening leans in with wide eyes and the waves", () => {
    const pose = run(1000, "listening").at(-1)!;
    expect(pose.tilt).toBeGreaterThan(0.1);
    expect(pose.dip).toBeGreaterThan(1);
    expect(pose.listen).toBeGreaterThan(0.99);
    expect(pose.think).toBeLessThan(0.01);
  });

  it("thinking looks up with the dots", () => {
    const pose = run(1000, "thinking").at(-1)!;
    expect(pose.lookY).toBeLessThan(-0.7);
    expect(pose.think).toBeGreaterThan(0.99);
  });

  it("eases between states instead of jumping", () => {
    const poses = run(1000, (t) => (t < 500 ? "idle" : "listening"));
    for (let i = 1; i < poses.length; i++) {
      expect(Math.abs(poses[i].dip - poses[i - 1].dip)).toBeLessThan(0.3);
      expect(Math.abs(poses[i].listen - poses[i - 1].listen)).toBeLessThan(0.15);
    }
  });

  it("only speaking opens the mouth", () => {
    expect(run(500, "idle", () => 1).at(-1)!.mouth).toBe(0);
    expect(run(500, "speaking", () => 1).at(-1)!.mouth).toBeGreaterThan(0.95);
    expect(run(500, "speaking", () => 0).at(-1)!.mouth).toBe(0);
  });

  it("closes the mouth after speaking", () => {
    const pose = run(1000, (t) => (t < 500 ? "speaking" : "idle"), () => 1).at(-1)!;
    expect(pose.mouth).toBeLessThan(0.02);
  });

  it("happy hops and sparkles once, then looks idle", () => {
    const poses = run(JOY_MS + 600, "happy");
    expect(Math.min(...poses.map((p) => p.hop))).toBeLessThan(-5);
    expect(Math.max(...poses.map((p) => p.sparkle))).toBeGreaterThan(0.9);
    const after = poses.at(-1)!;
    expect(after.joy).toBe(1);
    expect(after.hop).toBe(0);
    expect(after.smile).toBeLessThan(0.05);
    expect(after.sparkle).toBeLessThan(0.05);
  });

  it("happy plays again once the state has changed and come back", () => {
    const poses = run(4000, (t) => (t < 2000 ? "happy" : t < 2500 ? "idle" : "happy"));
    const hops = poses.filter((p) => p.hop < -5).map((p) => p.t);
    expect(hops.some((t) => t < 2000)).toBe(true);
    expect(hops.some((t) => t > 2500)).toBe(true);
  });

  it("sleeping shuts the eyes, without blinking, and lets the z's rise", () => {
    const poses = run(BLINK_MAX_MS * 2, "sleeping");
    const settled = poses.filter((p) => p.t > 1000);
    expect(Math.max(...settled.map((p) => p.eyes))).toBeLessThan(0.01);
    expect(settled.at(-1)!.sleep).toBeCloseTo(1, 2);
    expect(settled.at(-1)!.dip).toBeGreaterThan(1.9);
    // Waking: the eyes open again.
    const woken = run(2000, (t) => (t < 1000 ? "sleeping" : "idle")).at(-1)!;
    expect(woken.eyes).toBeGreaterThan(0.95);
    expect(woken.sleep).toBeLessThan(0.01);
  });

  it("draws asleep when still, everything else at rest", () => {
    expect(stillPose("sleeping")).toMatchObject({ eyes: 0, sleep: 1 });
    expect(stillPose("speaking")).toBe(REST_POSE);
  });

  it("takes a long gap (hidden tab) as one short step", () => {
    const animator = createAnimator(() => 0.5);
    animator.step(0, "idle", 0);
    const pose = animator.step(60_000, "listening", 0);
    expect(pose.listen).toBeLessThan(0.6);
  });
});

describe("followMouth", () => {
  it("opens faster than it closes", () => {
    const opened = followMouth(0, 1, 30);
    const closed = 1 - followMouth(1, 0, 30);
    expect(opened).toBeGreaterThan(closed * 2);
  });
});
