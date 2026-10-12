import { describe, expect, it, vi } from "vitest";

import { voiceLevel } from "@/lib/voice-level";

import {
  createCallPlayer,
  createFramer,
  createPlaybackClock,
  createResampler,
  FRAME_MS,
  fromPcm16,
  toPcm16,
} from "./realtime-audio";

const round = (samples: Float32Array) => Array.from(samples).map((x) => Number(x.toFixed(3)));

/** Feeds `input` to a fresh resampler in blocks of `block` and joins the output. */
function resampleInBlocks(input: Float32Array, from: number, to: number, block: number) {
  const resample = createResampler(from, to);
  const out: number[] = [];
  for (let i = 0; i < input.length; i += block) {
    out.push(...resample(input.subarray(i, i + block)));
  }
  return out;
}

describe("createResampler", () => {
  it("averages each window going down (48 kHz → 16 kHz)", () => {
    const resample = createResampler(48000, 16000);
    expect(round(resample(Float32Array.from([0, 0.3, 0.6, 0.9, 0.9, 0.9])))).toEqual([0.3, 0.9]);
  });

  it("carries a window that spans two blocks over to the next", () => {
    const resample = createResampler(48000, 16000);
    expect(round(resample(Float32Array.from([0, 0.3, 0.6, 0.9])))).toEqual([0.3]);
    expect(round(resample(Float32Array.from([0.9, 0.9])))).toEqual([0.9]);
  });

  it("gives the same samples whatever the block size", () => {
    const input = Float32Array.from({ length: 4410 }, (_, i) => Math.sin(i / 7));
    const whole = resampleInBlocks(input, 44100, 24000, input.length);
    expect(resampleInBlocks(input, 44100, 24000, 128)).toEqual(whole);
  });

  it("does not drift on an uneven ratio (44.1 kHz → 24 kHz)", () => {
    const out = resampleInBlocks(new Float32Array(44100 * 10), 44100, 24000, 128);
    expect(Math.abs(out.length - 240000)).toBeLessThanOrEqual(1);
  });

  it("interpolates going up across blocks", () => {
    const resample = createResampler(8000, 16000);
    expect(Array.from(resample(Float32Array.from([0, 1])))).toEqual([0, 0.5]);
    expect(Array.from(resample(Float32Array.from([0])))).toEqual([1, 0.5]);
  });

  it("copies at the same rate", () => {
    const input = Float32Array.from([0.1, 0.2]);
    const out = createResampler(24000, 24000)(input);
    expect(out).toEqual(input);
    expect(out).not.toBe(input);
  });
});

describe("PCM16", () => {
  it("encodes little-endian and clips", () => {
    const view = new DataView(toPcm16(Float32Array.from([0, 1, -1, 2, -2, 0.5])));
    expect(Array.from({ length: 6 }, (_, i) => view.getInt16(i * 2, true))).toEqual([
      0, 32767, -32768, 32767, -32768, 16383,
    ]);
  });

  it("decodes back to about the same samples", () => {
    const samples = Float32Array.from([0, 0.25, -0.5, 0.999]);
    expect(round(fromPcm16(toPcm16(samples)))).toEqual(round(samples));
  });

  it("ignores a trailing odd byte", () => {
    expect(fromPcm16(new ArrayBuffer(5))).toHaveLength(2);
  });
});

describe("createFramer", () => {
  it("hands out frames of 100 ms only once full", () => {
    const onFrame = vi.fn();
    const frame = createFramer(16000, onFrame);
    const size = (16000 * FRAME_MS) / 1000;
    frame(new Float32Array(size - 1));
    expect(onFrame).not.toHaveBeenCalled();
    frame(new Float32Array(size * 2));
    expect(onFrame).toHaveBeenCalledTimes(2);
    expect((onFrame.mock.calls[0][0] as ArrayBuffer).byteLength).toBe(size * 2);
  });

  it("keeps the samples in order across frames", () => {
    const frames: ArrayBuffer[] = [];
    const frame = createFramer(100, (f) => frames.push(f)); // 10 samples a frame
    frame(Float32Array.from({ length: 15 }, (_, i) => i / 100));
    frame(Float32Array.from({ length: 5 }, (_, i) => (15 + i) / 100));
    expect(frames.map((f) => round(fromPcm16(f)).map((x) => Math.round(x * 100)))).toEqual([
      [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
      [10, 11, 12, 13, 14, 15, 16, 17, 18, 19],
    ]);
  });
});

describe("createPlaybackClock", () => {
  it("starts a little ahead, then joins chunks end to end", () => {
    const clock = createPlaybackClock();
    expect(clock.schedule(10, 0.5)).toBeCloseTo(10.05);
    expect(clock.schedule(10.1, 0.5)).toBeCloseTo(10.55);
    expect(clock.busy(10.9)).toBe(true);
    expect(clock.busy(11.1)).toBe(false);
  });

  it("starts afresh once playback ran dry", () => {
    const clock = createPlaybackClock();
    clock.schedule(0, 0.2);
    expect(clock.schedule(5, 0.2)).toBeCloseTo(5.05);
  });

  it("forgets the queue on clear", () => {
    const clock = createPlaybackClock();
    clock.schedule(0, 10);
    clock.clear();
    expect(clock.busy(1)).toBe(false);
    expect(clock.schedule(1, 0.2)).toBeCloseTo(1.05);
  });

  it("counts what was heard of the current reply", () => {
    const clock = createPlaybackClock();
    expect(clock.playedMs(1)).toBe(0);
    clock.schedule(0, 1); // plays 0.05–1.05
    clock.schedule(0.5, 1); // then 1.05–2.05
    expect(clock.playedMs(0.55)).toBe(500);
    expect(clock.playedMs(3)).toBe(2000); // no more than was queued
    clock.newReply();
    clock.schedule(3, 1);
    expect(clock.playedMs(3.15)).toBe(100);
  });
});

describe("createCallPlayer", () => {
  it("plays through an analyser the avatar's mouth follows, until it closes", () => {
    const connected: unknown[] = [];
    let analyser: { connect: (to: unknown) => void } | null = null;
    vi.stubGlobal(
      "AudioContext",
      class {
        currentTime = 0;
        destination = { name: "speakers" };
        resume = () => Promise.resolve();
        close = () => Promise.resolve();
        createAnalyser = () =>
          (analyser = {
            connect: (to: unknown) => connected.push(["analyser", to]),
            getFloatTimeDomainData: (samples: Float32Array) => samples.fill(0.3),
          } as never);
        createBuffer = () => ({ duration: 0.1, copyToChannel: () => {} });
        createBufferSource = () => ({
          connect: (to: unknown) => connected.push(["source", to]),
          start: () => {},
          stop: () => {},
        });
      },
    );
    const player = createCallPlayer();
    player.play(toPcm16(Float32Array.from([0.5, -0.5])), 24000);
    expect(connected).toEqual([
      ["analyser", { name: "speakers" }],
      ["source", analyser],
    ]);
    expect(voiceLevel(0)).toBeCloseTo(1);
    player.close();
    expect(voiceLevel(0)).toBe(0);
    vi.unstubAllGlobals();
  });
});
