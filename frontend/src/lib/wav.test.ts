import { describe, expect, it } from "vitest";

import { concatSamples, encodeWav, recordingToWav, resample, WAV_SAMPLE_RATE } from "./wav";

const ascii = (view: DataView, offset: number, length: number) =>
  String.fromCharCode(...Array.from({ length }, (_, i) => view.getUint8(offset + i)));

describe("concatSamples", () => {
  it("joins chunks in order", () => {
    expect(
      Array.from(concatSamples([Float32Array.from([1, 2]), Float32Array.from([3])])),
    ).toEqual([1, 2, 3]);
  });
});

describe("resample", () => {
  it("averages each window going down (48 kHz → 16 kHz)", () => {
    const out = resample(Float32Array.from([0, 0.3, 0.6, 0.9, 0.9, 0.9]), 48000, 16000);
    expect(Array.from(out).map((x) => Number(x.toFixed(3)))).toEqual([0.3, 0.9]);
  });

  it("handles a ratio that is not a whole number (44.1 kHz)", () => {
    expect(resample(new Float32Array(44100), 44100, 16000)).toHaveLength(16000);
  });

  it("interpolates going up", () => {
    expect(Array.from(resample(Float32Array.from([0, 1]), 8000, 16000))).toEqual([0, 0.5, 1, 1]);
  });

  it("copies at the same rate", () => {
    const input = Float32Array.from([0.1, 0.2]);
    const out = resample(input, 16000, 16000);
    expect(out).toEqual(input);
    expect(out).not.toBe(input);
  });
});

describe("encodeWav", () => {
  it("writes a 16 kHz mono 16-bit PCM header", () => {
    const view = new DataView(encodeWav(new Float32Array(10), 16000));
    expect(view.byteLength).toBe(44 + 20);
    expect(ascii(view, 0, 4)).toBe("RIFF");
    expect(view.getUint32(4, true)).toBe(36 + 20);
    expect(ascii(view, 8, 8)).toBe("WAVEfmt ");
    expect(view.getUint16(20, true)).toBe(1);
    expect(view.getUint16(22, true)).toBe(1);
    expect(view.getUint32(24, true)).toBe(16000);
    expect(view.getUint32(28, true)).toBe(32000);
    expect(view.getUint16(32, true)).toBe(2);
    expect(view.getUint16(34, true)).toBe(16);
    expect(ascii(view, 36, 4)).toBe("data");
    expect(view.getUint32(40, true)).toBe(20);
  });

  it("scales samples to 16 bits and clips beyond full scale", () => {
    const view = new DataView(encodeWav(Float32Array.from([1, -1, 0.5, 2, -3]), 16000));
    const pcm = [0, 1, 2, 3, 4].map((i) => view.getInt16(44 + i * 2, true));
    expect(pcm).toEqual([32767, -32768, 16383, 32767, -32768]);
  });
});

describe("recordingToWav", () => {
  it("resamples to 16 kHz and cuts at the limit", () => {
    const second = new Float32Array(48000);
    const view = new DataView(recordingToWav([second, second, second], 48000, 2));
    expect(view.getUint32(24, true)).toBe(WAV_SAMPLE_RATE);
    expect(view.getUint32(40, true)).toBe(2 * WAV_SAMPLE_RATE * 2);
  });
});
