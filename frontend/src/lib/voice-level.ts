/**
 * How loud the tutor is right now, 0..1, for the avatar's mouth (ADR 0032 §4). One source
 * at a time feeds it: the server's read-aloud audio and the call player through an
 * `AnalyserNode`, the browser's voices through their word `boundary` events (no audio to
 * measure there). The avatar reads it every frame instead of through React state.
 */

/** The level now (0..1) at `now` (ms, `performance.now()`). */
export type LevelSource = (now: number) => number;

let current: LevelSource | null = null;
const activeListeners = new Set<() => void>();

function setCurrent(source: LevelSource | null) {
  const was = current !== null;
  current = source;
  if (was !== (source !== null)) activeListeners.forEach((listener) => listener());
}

/**
 * Makes `source` the one the avatar follows; the returned function stops it, unless
 * another source has taken over since.
 */
export function setLevelSource(source: LevelSource): () => void {
  setCurrent(source);
  return () => {
    if (current === source) setCurrent(null);
  };
}

/** Whether the tutor's voice is playing now (a reading, or a call): the pet talks. */
export const voiceActive = () => current !== null;

/** Calls `listener` whenever the voice starts or stops; returns how to stop listening. */
export function subscribeVoiceActive(listener: () => void): () => void {
  activeListeners.add(listener);
  return () => activeListeners.delete(listener);
}

/** The tutor's level now: 0 when nothing is speaking. */
export function voiceLevel(now: number): number {
  return current ? clamp01(current(now)) : 0;
}

// How many animated avatars are on the page: the read-aloud audio is routed through an
// analyser only when one is there to watch it.
let watchers = 0;

/** Marks one animated avatar as watching the level; the returned function unmarks it. */
export function watchLevel(): () => void {
  watchers++;
  let done = false;
  return () => {
    if (!done) watchers--;
    done = true;
  };
}

export const levelWatched = () => watchers > 0;

// Below this RMS is silence (breath, a quiet tail); at the top one it's loud speech.
export const LEVEL_GATE = 0.02;
const LEVEL_FULL = 0.3;

/**
 * An RMS of speech mapped to 0..1: nothing under the gate, then on a log scale, as loudness
 * is heard, so quiet syllables still move the mouth.
 */
export function levelFromRms(rms: number): number {
  if (!(rms > LEVEL_GATE)) return 0;
  return clamp01(Math.log(rms / LEVEL_GATE) / Math.log(LEVEL_FULL / LEVEL_GATE));
}

/** The RMS of what `analyser` hears now, as a level source. */
export function analyserLevel(analyser: AnalyserNode): LevelSource {
  const samples = new Float32Array(analyser.fftSize);
  return () => {
    analyser.getFloatTimeDomainData(samples);
    let sum = 0;
    for (const sample of samples) sum += sample * sample;
    return levelFromRms(Math.sqrt(sum / samples.length));
  };
}

// A word opens the mouth this wide and it closes over about this long.
const PULSE = 0.85;
const PULSE_DECAY_MS = 140;
// With no boundary events at all (some voices send none), the mouth flaps at about 4 syllables
// a second instead.
const FLAP_HZ = 4;

export type BrowserMouth = {
  /** The browser reached a word. */
  pulse: (now: number) => void;
  level: LevelSource;
};

/** A level for a browser voice, which gives words but no audio: each word opens the mouth. */
export function browserMouth(start: number): BrowserMouth {
  let last: number | null = null;
  return {
    pulse(now) {
      last = now;
    },
    level(now) {
      if (last !== null) return PULSE * Math.exp(-Math.max(0, now - last) / PULSE_DECAY_MS);
      const t = (now - start) / 1000;
      // Two slow waves over the flap, so it doesn't look like a metronome.
      const flap = Math.abs(Math.sin(Math.PI * FLAP_HZ * t));
      return flap * (0.55 + 0.3 * Math.sin(2 * Math.PI * 0.7 * t) + 0.15 * Math.sin(2 * Math.PI * 1.9 * t));
    },
  };
}

const clamp01 = (x: number) => (x > 1 ? 1 : x > 0 ? x : 0);
