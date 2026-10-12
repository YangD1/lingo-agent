/**
 * How the tutor cat moves (ADR 0032 §4): a pure animator that turns what the tutor is doing,
 * the time and the voice level into one frame's pose. Drawing is `avatar-draw.ts`.
 */

/** What the tutor is doing: waiting, hearing the learner, waiting on the reply, talking, glad. */
export type AvatarState = "idle" | "listening" | "thinking" | "speaking" | "happy";

export type Pose = {
  /** Seconds since the animator started: for what loops (breath, tail, dots, waves). */
  time: number;
  /** Body and head lifted by this much (box units, up is negative): the happy hop. */
  hop: number;
  /** Head tilt, radians (positive leans right). */
  tilt: number;
  /** Head moved down by this much: leaning in to listen. */
  dip: number;
  /** Eyes: 0 shut, 1 open, a bit more when listening. */
  eyes: number;
  /** 0..1: eyes curved into a smile (^^). */
  smile: number;
  /** Where the eyes look, each -1..1 (up is negative). */
  lookX: number;
  lookY: number;
  /** How open the mouth is, 0..1. */
  mouth: number;
  /** 0..1: how much of the listening waves, the thinking dots, the happy sparkles show. */
  listen: number;
  think: number;
  sparkle: number;
  /** 0..1 through the happy hop and sparkles; 1 once they are over. */
  joy: number;
};

/** The pose drawn when nothing moves: reduced motion, animation off, or before any frame. */
export const REST_POSE: Pose = {
  time: 0,
  hop: 0,
  tilt: 0,
  dip: 0,
  eyes: 1,
  smile: 0,
  lookX: 0,
  lookY: 0,
  mouth: 0,
  listen: 0,
  think: 0,
  sparkle: 0,
  joy: 1,
};

type Target = Pick<Pose, "tilt" | "dip" | "eyes" | "smile" | "lookX" | "lookY" | "listen" | "think" | "sparkle">;

const IDLE: Target = { tilt: 0, dip: 0, eyes: 1, smile: 0, lookX: 0, lookY: 0, listen: 0, think: 0, sparkle: 0 };

const TARGETS: Record<Exclude<AvatarState, "happy">, Target> = {
  idle: IDLE,
  listening: { ...IDLE, tilt: 0.12, dip: 1.5, eyes: 1.12, lookX: 0.3, listen: 1 },
  thinking: { ...IDLE, tilt: -0.08, eyes: 0.9, lookX: 0.6, lookY: -0.8, think: 1 },
  speaking: IDLE,
};

// Changes of state ease over about this long, so the cat never jumps.
export const SETTLE_MS = 150;
// The mouth opens fast and closes slower, so it doesn't chatter.
export const MOUTH_OPEN_MS = 30;
export const MOUTH_CLOSE_MS = 120;
// A blink comes every 3–6 s and lasts this long.
export const BLINK_MIN_MS = 3000;
export const BLINK_MAX_MS = 6000;
export const BLINK_MS = 160;
// The happy hop, then the sparkles fade; after that the cat is back to idle.
export const HOP_MS = 500;
export const JOY_MS = 1400;
const HOP_HEIGHT = 6;
// A frame after a long gap (the tab was hidden) moves at most this far.
const MAX_STEP_MS = 100;

/** Moves `from` toward `to` as an exponential ease with time constant `tau` over `dt`. */
export function ease(from: number, to: number, dt: number, tau: number): number {
  return from + (to - from) * (1 - Math.exp(-dt / tau));
}

/** The mouth following the voice level: fast to open, slower to close. */
export function followMouth(mouth: number, level: number, dt: number): number {
  return ease(mouth, level, dt, level > mouth ? MOUTH_OPEN_MS : MOUTH_CLOSE_MS);
}

/** How shut the eyes are `ms` into a blink: closing then opening, 0 → 1 → 0. */
export function blinkAt(ms: number): number {
  if (ms < 0 || ms >= BLINK_MS) return 0;
  return Math.sin((Math.PI * ms) / BLINK_MS);
}

export type Animator = {
  /** The pose at `now` (ms) doing `state`, with the tutor's voice at `level` (0..1). */
  step(now: number, state: AvatarState, level: number): Pose;
};

/** A fresh animator; `random` (0..1) spaces the blinks. */
export function createAnimator(random: () => number = Math.random): Animator {
  let start: number | null = null;
  let last = 0;
  let shown: AvatarState | null = null;
  let since = 0;
  let nextBlink = 0;
  const pose: Pose = { ...REST_POSE, joy: 1 };
  const blinkGap = () => BLINK_MIN_MS + random() * (BLINK_MAX_MS - BLINK_MIN_MS);

  return {
    step(now, state, level) {
      if (start === null) {
        start = last = now;
        nextBlink = now + blinkGap();
      }
      const dt = Math.min(Math.max(now - last, 0), MAX_STEP_MS);
      last = now;
      if (state !== shown) {
        shown = state;
        since = now;
      }

      // Happy plays once: the hop and sparkles, then it looks idle until the state changes.
      const joyMs = state === "happy" ? now - since : JOY_MS;
      const joy = Math.min(joyMs / JOY_MS, 1);
      const glad = state === "happy" && joy < 1;
      const target: Target = glad
        ? { ...IDLE, smile: 1, sparkle: 1 }
        : state === "happy"
          ? IDLE
          : TARGETS[state];

      for (const key of Object.keys(target) as (keyof Target)[]) {
        pose[key] = ease(pose[key], target[key], dt, SETTLE_MS);
      }
      pose.mouth = followMouth(pose.mouth, state === "speaking" ? level : 0, dt);
      pose.hop = joyMs < HOP_MS ? -HOP_HEIGHT * Math.sin((Math.PI * joyMs) / HOP_MS) : 0;
      pose.joy = joy;
      pose.time = (now - start) / 1000;
      if (now >= nextBlink + BLINK_MS) nextBlink = now + blinkGap();
      // On top of the eased pose, not into it: the blink, and talking's small nod.
      const nod = state === "speaking" ? 0.04 * Math.sin(pose.time * 5) * pose.mouth : 0;
      return { ...pose, tilt: pose.tilt + nod, eyes: pose.eyes * (1 - blinkAt(now - nextBlink)) };
    },
  };
}
