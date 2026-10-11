/**
 * Audio of a realtime call (ADR 0030 §1, Q60b, Q62c). The backend never touches the
 * audio: the browser sends the learner's voice as PCM16 mono at the rate `ready` names
 * (`input_rate`) and plays the tutor's PCM16 at `output_rate`. Echo cancellation is the
 * browser's (`openMicTap`); barge-in is the vendor's VAD, on whose `speech_started` the
 * page stops playing at once.
 */

import { meterLevel, rmsDbfs } from "@/components/chat/use-recorder";
import { type MicTap, openMicTap } from "@/lib/mic-tap";

/** The learner's audio goes out in frames of 100 ms. */
export const FRAME_MS = 100;
// The first reply chunk starts this far ahead so the next one is there in time.
const PLAYBACK_LEAD_SECONDS = 0.05;

/**
 * Resampling across blocks: the worklet's blocks are short (128 samples), so resampling
 * each on its own would leave a seam at every boundary and drift on uneven ratios
 * (44.1 → 24 kHz). This one carries the unused input over and places every window by
 * its exact position in the whole stream.
 * Going down it averages the input each output sample covers (a crude low-pass, as
 * `wav.ts`); going up it interpolates linearly.
 */
export function createResampler(fromRate: number, toRate: number) {
  let pending = new Float32Array(0);
  let dropped = 0; // input samples before `pending`
  let next = 0; // index of the next output sample
  // Output sample n covers input [n * from / to, (n + 1) * from / to): exact in integers,
  // so the block size never shifts a window.
  const at = (n: number) => Math.floor((n * fromRate) / toRate) - dropped;
  return (input: Float32Array): Float32Array => {
    if (fromRate === toRate) return input.slice();
    const joined = new Float32Array(pending.length + input.length);
    joined.set(pending);
    joined.set(input, pending.length);
    const out: number[] = [];
    for (;;) {
      const start = at(next);
      if (fromRate > toRate) {
        const end = Math.max(start + 1, at(next + 1));
        if (end > joined.length) break;
        let sum = 0;
        for (let j = start; j < end; j++) sum += joined[j];
        out.push(sum / (end - start));
      } else {
        if (start + 1 >= joined.length) break;
        const fraction = ((next * fromRate) % toRate) / toRate;
        out.push(joined[start] + (joined[start + 1] - joined[start]) * fraction);
      }
      next++;
    }
    const used = Math.max(0, at(next));
    pending = joined.slice(used);
    dropped += used;
    return Float32Array.from(out);
  };
}

/** Samples (-1..1, clipped beyond) as little-endian 16-bit PCM. */
export function toPcm16(samples: Float32Array): ArrayBuffer {
  const buffer = new ArrayBuffer(samples.length * 2);
  const view = new DataView(buffer);
  for (let i = 0; i < samples.length; i++) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  }
  return buffer;
}

/** Little-endian 16-bit PCM as samples in -1..1. */
export function fromPcm16(data: ArrayBuffer): Float32Array<ArrayBuffer> {
  const view = new DataView(data);
  const out = new Float32Array(Math.floor(data.byteLength / 2));
  for (let i = 0; i < out.length; i++) out[i] = view.getInt16(i * 2, true) / 0x8000;
  return out;
}

/** Collects samples and hands out PCM16 frames of `FRAME_MS` at `rate`. */
export function createFramer(rate: number, onFrame: (frame: ArrayBuffer) => void) {
  const size = Math.round((rate * FRAME_MS) / 1000);
  const frame = new Float32Array(size);
  let filled = 0;
  return (samples: Float32Array) => {
    let offset = 0;
    while (offset < samples.length) {
      const take = Math.min(size - filled, samples.length - offset);
      frame.set(samples.subarray(offset, offset + take), filled);
      filled += take;
      offset += take;
      if (filled === size) {
        onFrame(toPcm16(frame));
        filled = 0;
      }
    }
  };
}

/**
 * When each chunk of the tutor's reply starts: right after the previous one so they
 * join without gaps, or a little ahead of now when playback has run dry. It also knows
 * how much of the current reply has been heard, which OpenAI uses to forget the rest
 * when the learner cuts in. `clear` forgets the queue (barge-in).
 */
export function createPlaybackClock() {
  let next = 0;
  let replyStart: number | null = null;
  return {
    schedule(now: number, seconds: number): number {
      const start = Math.max(next, now + PLAYBACK_LEAD_SECONDS);
      replyStart ??= start;
      next = start + seconds;
      return start;
    },
    /** Whether anything scheduled is still playing at `now`. */
    busy: (now: number) => next > now,
    /** Milliseconds of the current reply played by `now`. */
    playedMs: (now: number) =>
      replyStart === null ? 0 : Math.max(0, Math.round((Math.min(now, next) - replyStart) * 1000)),
    /** The next chunk starts another reply. */
    newReply() {
      replyStart = null;
    },
    clear() {
      next = 0;
      replyStart = null;
    },
  };
}

export type CallMicrophone = {
  /** Starts sending frames at `rate`, the call's `input_rate`. */
  send: (rate: number, onFrame: (frame: ArrayBuffer) => void) => void;
  /** Muted: no frames go out (nothing is billed) and the level reads 0. */
  setMuted: (muted: boolean) => void;
  close: () => void;
};

/**
 * The learner's microphone for a call. Opened on the connect click, before `ready`, so
 * the permission prompt comes first; frames flow once `send` knows the vendor's rate.
 * `onLevel` gets the loudness (0..1) of every block while not muted.
 */
export async function openCallMicrophone(
  onLevel: (level: number) => void,
): Promise<CallMicrophone> {
  const tap: MicTap = await openMicTap();
  let muted = false;
  let forward: ((samples: Float32Array) => void) | null = null;
  tap.onSamples = (samples) => {
    if (muted) return;
    onLevel(meterLevel(rmsDbfs(samples)));
    forward?.(samples);
  };
  tap.start();
  return {
    send(rate, onFrame) {
      const resample = createResampler(tap.rate, rate);
      const frame = createFramer(rate, onFrame);
      forward = (samples) => frame(resample(samples));
    },
    setMuted(value) {
      muted = value;
      tap.stream.getAudioTracks().forEach((track) => (track.enabled = !value));
      if (value) onLevel(0);
    },
    close() {
      forward = null;
      tap.close();
    },
  };
}

export type CallPlayer = {
  /** Queues one chunk of the tutor's PCM16 at `rate`. */
  play: (data: ArrayBuffer, rate: number) => void;
  /** Stops at once and drops what is queued (the learner started talking). */
  clear: () => void;
  /** Whether the tutor's voice is still playing. */
  busy: () => boolean;
  /** Milliseconds heard of the reply now playing. */
  playedMs: () => number;
  /** The tutor finished a reply: the next chunk starts another. */
  newReply: () => void;
  close: () => void;
};

/** Plays the tutor. Create it on the connect click: browsers only start audio on a gesture. */
export function createCallPlayer(): CallPlayer {
  const context = new AudioContext();
  void context.resume();
  const clock = createPlaybackClock();
  const sources = new Set<AudioBufferSourceNode>();
  const clear = () => {
    for (const source of sources) {
      source.onended = null;
      source.stop();
    }
    sources.clear();
    clock.clear();
  };
  return {
    play(data, rate) {
      const samples = fromPcm16(data);
      if (samples.length === 0) return;
      const buffer = context.createBuffer(1, samples.length, rate);
      buffer.copyToChannel(samples, 0);
      const source = context.createBufferSource();
      source.buffer = buffer;
      source.connect(context.destination);
      source.onended = () => sources.delete(source);
      sources.add(source);
      source.start(clock.schedule(context.currentTime, buffer.duration));
    },
    clear,
    busy: () => clock.busy(context.currentTime),
    playedMs: () => clock.playedMs(context.currentTime),
    newReply: () => clock.newReply(),
    close() {
      clear();
      void context.close();
    },
  };
}
