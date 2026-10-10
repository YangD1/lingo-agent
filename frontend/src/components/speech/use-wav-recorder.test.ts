import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { createLevelTracker, MAX_SHADOWING_SECONDS, useWavRecorder } from "./use-wav-recorder";

const RATE = 16000;

describe("createLevelTracker", () => {
  it("counts voiced time and the peak per 50 ms window", () => {
    const levels: number[] = [];
    const tracker = createLevelTracker(RATE, (l) => levels.push(l));
    tracker.push(new Float32Array(RATE / 2).fill(0.1)); // 0.5 s at -20 dBFS
    tracker.push(new Float32Array(RATE / 2)); // 0.5 s of silence
    const summary = tracker.summary();
    expect(summary.peakDb).toBeCloseTo(-20);
    expect(summary.voicedSeconds).toBeCloseTo(0.5);
    expect(levels).toHaveLength(20);
  });

  it("keeps a partial window for the next block", () => {
    const tracker = createLevelTracker(RATE, () => {});
    tracker.push(new Float32Array(500).fill(0.1));
    expect(tracker.summary().voicedSeconds).toBe(0);
    tracker.push(new Float32Array(300).fill(0.1));
    expect(tracker.summary().voicedSeconds).toBeCloseTo(0.05);
  });
});

// Just enough of Web Audio for the hook: the worklet node's port is how samples arrive.
let tap: { port: { onmessage: ((e: { data: Float32Array }) => void) | null } } | null;
const trackStop = vi.fn();
const contextClose = vi.fn();

function node() {
  return { connect: (next: unknown) => next, disconnect: vi.fn() };
}

class FakeContext {
  sampleRate = RATE;
  destination = {};
  audioWorklet = { addModule: vi.fn(async () => {}) };
  createMediaStreamSource = () => node();
  createGain = () => ({ ...node(), gain: { value: 1 } });
  resume = vi.fn(async () => {});
  close = contextClose;
}

class FakeWorkletNode {
  port = { onmessage: null };
  connect = (next: unknown) => next;
  disconnect = vi.fn();
}

// Records the node the hook creates.
const WorkletNode = vi.fn(function () {
  tap = new FakeWorkletNode();
  return tap;
});

function send(samples: Float32Array) {
  act(() => tap!.port.onmessage!({ data: samples }));
}

const getUserMedia = vi.fn();

beforeEach(() => {
  tap = null;
  vi.stubGlobal("AudioContext", FakeContext);
  vi.stubGlobal("AudioWorkletNode", WorkletNode);
  Object.defineProperty(navigator, "mediaDevices", {
    configurable: true,
    value: { getUserMedia },
  });
  getUserMedia.mockResolvedValue({ getTracks: () => [{ stop: trackStop }] });
  URL.createObjectURL = vi.fn(() => "blob:tap");
  URL.revokeObjectURL = vi.fn();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

async function started(onRecorded = vi.fn()) {
  const hook = renderHook(() => useWavRecorder(onRecorded));
  await act(() => hook.result.current.start());
  return { ...hook, onRecorded };
}

describe("useWavRecorder", () => {
  it("hands over a 16 kHz WAV file and releases the microphone", async () => {
    const { result, onRecorded } = await started();
    expect(result.current.recording).toBe(true);
    send(new Float32Array(RATE).fill(0.1));
    expect(result.current.seconds).toBe(1);
    act(() => result.current.stop());

    expect(result.current.recording).toBe(false);
    expect(trackStop).toHaveBeenCalled();
    expect(contextClose).toHaveBeenCalled();
    const file: File = onRecorded.mock.calls[0][0];
    expect(file.type).toBe("audio/wav");
    expect(file.name).toMatch(/^shadowing-.*\.wav$/);
    expect(file.size).toBe(44 + RATE * 2);
  });

  it("drops a silent recording", async () => {
    const { result, onRecorded } = await started();
    send(new Float32Array(RATE));
    act(() => result.current.stop());
    expect(onRecorded).not.toHaveBeenCalled();
    expect(result.current.error).toBe("recording_silent");
  });

  it("treats a recording that never got samples as silent", async () => {
    const { result, onRecorded } = await started();
    act(() => result.current.stop());
    expect(onRecorded).not.toHaveBeenCalled();
    expect(result.current.error).toBe("recording_silent");
  });

  it("stops by itself at 30 seconds", async () => {
    const { result, onRecorded } = await started();
    send(new Float32Array(MAX_SHADOWING_SECONDS * RATE).fill(0.1));
    expect(result.current.recording).toBe(false);
    expect((onRecorded.mock.calls[0][0] as File).size).toBe(44 + MAX_SHADOWING_SECONDS * RATE * 2);
  });

  it("keeps nothing when cancelled", async () => {
    const { result, onRecorded } = await started();
    send(new Float32Array(RATE).fill(0.1));
    act(() => result.current.cancel());
    expect(onRecorded).not.toHaveBeenCalled();
    expect(result.current.error).toBeNull();
    expect(trackStop).toHaveBeenCalled();
  });

  it("releases the microphone when the page goes away", async () => {
    const { unmount, onRecorded } = await started();
    send(new Float32Array(RATE).fill(0.1));
    unmount();
    expect(trackStop).toHaveBeenCalled();
    expect(onRecorded).not.toHaveBeenCalled();
  });

  it("reports a denied microphone", async () => {
    getUserMedia.mockRejectedValueOnce(new Error("NotAllowedError"));
    const { result } = await started();
    expect(result.current.error).toBe("microphone_denied");
    expect(result.current.recording).toBe(false);
  });

  it("reports browsers without AudioWorklet", async () => {
    vi.stubGlobal("AudioWorkletNode", undefined);
    const { result } = await started();
    expect(result.current.error).toBe("recording_unsupported");
    expect(getUserMedia).not.toHaveBeenCalled();
  });
});
