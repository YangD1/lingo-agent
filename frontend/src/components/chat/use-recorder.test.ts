import { describe, expect, it } from "vitest";

import { isSilentRecording, meterLevel, pickRecordingFormat, rmsDbfs } from "./use-recorder";

describe("pickRecordingFormat", () => {
  it("prefers webm/opus (Chrome, Firefox)", () => {
    expect(pickRecordingFormat(() => true)).toEqual({
      mimeType: "audio/webm;codecs=opus",
      extension: "webm",
    });
  });

  it("falls back to mp4 (Safari)", () => {
    expect(pickRecordingFormat((t) => t === "audio/mp4")).toEqual({
      mimeType: "audio/mp4",
      extension: "m4a",
    });
  });

  it("returns null when nothing is supported", () => {
    expect(pickRecordingFormat(() => false)).toBeNull();
  });
});

describe("rmsDbfs", () => {
  it("is 0 dBFS for a full-scale square wave", () => {
    expect(rmsDbfs(Float32Array.from([1, -1, 1, -1]))).toBeCloseTo(0);
  });

  it("drops 20 dB per tenfold smaller amplitude", () => {
    expect(rmsDbfs(Float32Array.from([0.01, -0.01]))).toBeCloseTo(-40);
  });

  it("is -Infinity for digital silence", () => {
    expect(rmsDbfs(new Float32Array(8))).toBe(-Infinity);
  });
});

describe("meterLevel", () => {
  it("maps -60..0 dBFS onto 0..1 and clamps", () => {
    expect(meterLevel(-Infinity)).toBe(0);
    expect(meterLevel(-30)).toBeCloseTo(0.5);
    expect(meterLevel(3)).toBe(1);
  });
});

describe("isSilentRecording", () => {
  it("keeps normal speech", () => {
    expect(isSilentRecording({ peakDb: -20, voicedSeconds: 1.2 })).toBe(false);
  });

  it("keeps a short answer such as 'yes'", () => {
    expect(isSilentRecording({ peakDb: -18, voicedSeconds: 0.35 })).toBe(false);
  });

  it("drops a recording that is never loud (the -60 dB clip whisper turned into 'ლლლ')", () => {
    expect(isSilentRecording({ peakDb: -60, voicedSeconds: 0 })).toBe(true);
  });

  it("drops a recording with only a click or a cough", () => {
    expect(isSilentRecording({ peakDb: -15, voicedSeconds: 0.1 })).toBe(true);
  });
});
