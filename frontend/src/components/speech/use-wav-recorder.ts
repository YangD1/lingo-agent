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
import { canTapMicrophone, type MicTap, MicTapError, openMicTap } from "@/lib/mic-tap";
import { recordingToWav } from "@/lib/wav";

/** Pronunciation assessment takes at most 30 seconds (ADR 0028 §5). */
export const MAX_SHADOWING_SECONDS = 30;
const METER_WINDOW_SECONDS = 0.05;

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

export const canRecordWav = canTapMicrophone;

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
    let mic: MicTap;
    try {
      mic = await openMicTap();
    } catch (e) {
      setError(e instanceof MicTapError ? e.code : "recording_unsupported");
      return;
    }
    const rate = mic.rate;
    const limit = MAX_SHADOWING_SECONDS * rate;
    const levels = createLevelTracker(rate, setLevel);
    const session: Session = {
      chunks: [],
      finish: (keep) => {
        if (sessionRef.current !== session) return;
        sessionRef.current = null;
        mic.close();
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
    mic.onSamples = (samples) => {
      session.chunks.push(samples);
      levels.push(samples);
      received += samples.length;
      setSeconds(Math.floor(received / rate));
      if (received >= limit) session.finish(true);
    };
    sessionRef.current = session;
    mic.start();
    setRecording(true);
  }, []);

  const stop = useCallback(() => sessionRef.current?.finish(true), []);
  const cancel = useCallback(() => sessionRef.current?.finish(false), []);

  // Leaving the page mid-recording releases the microphone and keeps nothing.
  useEffect(() => cancel, [cancel]);

  return { recording, seconds, level, error, start, stop, cancel };
}
