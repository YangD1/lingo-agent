"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import {
  isSilentRecording,
  meterLevel,
  rmsDbfs,
  VOICED_DB,
  type LevelSummary,
  type RecorderError,
} from "@/components/chat/use-recorder";
import { recordingToWav } from "@/lib/wav";

/** Pronunciation assessment takes at most 30 seconds (ADR 0028 §5). */
export const MAX_SHADOWING_SECONDS = 30;
const METER_WINDOW_SECONDS = 0.05;

// Copies each block of microphone samples (mixed down to mono) to the page. Loaded from
// a Blob URL so the worklet needs no separate build step.
const TAP_WORKLET = `
class LingoTap extends AudioWorkletProcessor {
  process(inputs) {
    const channels = inputs[0];
    if (channels && channels.length) {
      const mono = new Float32Array(channels[0].length);
      for (const channel of channels) {
        for (let i = 0; i < mono.length; i++) mono[i] += channel[i] / channels.length;
      }
      this.port.postMessage(mono, [mono.buffer]);
    }
    return true;
  }
}
registerProcessor("lingo-tap", LingoTap);
`;

/**
 * Loudness of the recording, measured on the samples themselves in windows of 50 ms:
 * the level bar and the silence check of `use-recorder.ts`.
 */
export function createLevelTracker(sampleRate: number, onLevel: (level: number) => void) {
  const windowSize = Math.max(1, Math.round(sampleRate * METER_WINDOW_SECONDS));
  const window = new Float32Array(windowSize);
  let filled = 0;
  const summary: LevelSummary = { peakDb: -Infinity, voicedSeconds: 0 };
  return {
    push(samples: Float32Array) {
      for (const sample of samples) {
        window[filled++] = sample;
        if (filled < windowSize) continue;
        filled = 0;
        const db = rmsDbfs(window);
        summary.peakDb = Math.max(summary.peakDb, db);
        if (db > VOICED_DB) summary.voicedSeconds += windowSize / sampleRate;
        onLevel(meterLevel(db));
      }
    },
    summary: (): LevelSummary => ({ ...summary }),
  };
}

export function canRecordWav(): boolean {
  return (
    typeof AudioContext !== "undefined" &&
    typeof AudioWorkletNode !== "undefined" &&
    !!navigator.mediaDevices?.getUserMedia
  );
}

type Session = {
  chunks: Float32Array[];
  finish: (keep: boolean) => void;
};

/**
 * Click to start, click to stop (or 30 s): `onRecorded` gets a 16 kHz mono WAV file
 * unless the recording was silent. Shadowing only; voice messages use `useRecorder`.
 */
export function useWavRecorder(onRecorded: (file: File) => void) {
  const [recording, setRecording] = useState(false);
  const [seconds, setSeconds] = useState(0);
  const [level, setLevel] = useState(0);
  const [error, setError] = useState<RecorderError | null>(null);
  const sessionRef = useRef<Session | null>(null);
  const onRecordedRef = useRef(onRecorded);
  useEffect(() => {
    onRecordedRef.current = onRecorded;
  });

  const start = useCallback(async () => {
    if (sessionRef.current) return;
    setError(null);
    if (!canRecordWav()) {
      setError("recording_unsupported");
      return;
    }
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
      });
    } catch {
      setError("microphone_denied");
      return;
    }
    const context = new AudioContext();
    const url = URL.createObjectURL(new Blob([TAP_WORKLET], { type: "text/javascript" }));
    let tap: AudioWorkletNode;
    try {
      await context.audioWorklet.addModule(url);
      tap = new AudioWorkletNode(context, "lingo-tap");
    } catch {
      stream.getTracks().forEach((track) => track.stop());
      void context.close();
      setError("recording_unsupported");
      return;
    } finally {
      URL.revokeObjectURL(url);
    }
    const source = context.createMediaStreamSource(stream);
    // Some browsers only run a worklet that reaches the output: route it there muted.
    const mute = context.createGain();
    mute.gain.value = 0;
    source.connect(tap).connect(mute).connect(context.destination);

    const rate = context.sampleRate;
    const limit = MAX_SHADOWING_SECONDS * rate;
    const levels = createLevelTracker(rate, setLevel);
    const session: Session = {
      chunks: [],
      finish: (keep) => {
        if (sessionRef.current !== session) return;
        sessionRef.current = null;
        tap.port.onmessage = null;
        source.disconnect();
        tap.disconnect();
        stream.getTracks().forEach((track) => track.stop());
        void context.close();
        setRecording(false);
        setSeconds(0);
        setLevel(0);
        if (!keep) return;
        // Nothing arrives while the context is suspended: that is no recording at all.
        if (session.chunks.length === 0 || isSilentRecording(levels.summary())) {
          setError("recording_silent");
          return;
        }
        const wav = recordingToWav(session.chunks, rate, MAX_SHADOWING_SECONDS);
        const stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-");
        onRecordedRef.current(new File([wav], `shadowing-${stamp}.wav`, { type: "audio/wav" }));
      },
    };
    let received = 0;
    tap.port.onmessage = (event: MessageEvent<Float32Array>) => {
      session.chunks.push(event.data);
      levels.push(event.data);
      received += event.data.length;
      setSeconds(Math.floor(received / rate));
      if (received >= limit) session.finish(true);
    };
    sessionRef.current = session;
    void context.resume();
    setRecording(true);
  }, []);

  const stop = useCallback(() => sessionRef.current?.finish(true), []);
  const cancel = useCallback(() => sessionRef.current?.finish(false), []);

  // Leaving the page mid-recording releases the microphone and keeps nothing.
  useEffect(() => cancel, [cancel]);

  return { recording, seconds, level, error, start, stop, cancel };
}
