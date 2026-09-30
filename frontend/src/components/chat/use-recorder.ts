"use client";

import { useCallback, useEffect, useRef, useState } from "react";

/** Voice messages stop here on their own (ADR 0008 §3: the backend only limits size). */
export const MAX_RECORDING_SECONDS = 180;

// Chrome and Firefox record webm/opus, Safari mp4/aac; the backend takes both as they are.
const FORMATS = [
  { mimeType: "audio/webm;codecs=opus", extension: "webm" },
  { mimeType: "audio/webm", extension: "webm" },
  { mimeType: "audio/mp4", extension: "m4a" },
  { mimeType: "audio/ogg;codecs=opus", extension: "ogg" },
] as const;

export function pickRecordingFormat(
  isTypeSupported: (type: string) => boolean,
): { mimeType: string; extension: string } | null {
  return FORMATS.find((f) => isTypeSupported(f.mimeType)) ?? null;
}

export type RecorderError = "microphone_denied" | "recording_unsupported" | "recording_silent";

// A recording counts as silent (and is not uploaded: whisper invents text for silence)
// when it is never louder than SILENT_PEAK_DB, or is louder than VOICED_DB for less
// than MIN_VOICED_SECONDS in total. Speech is usually -30 to -10 dBFS.
export const SILENT_PEAK_DB = -50;
export const VOICED_DB = -45;
export const MIN_VOICED_SECONDS = 0.3;
const METER_INTERVAL_MS = 50;

/** Loudness of one window of samples (-1..1) in dBFS; -Infinity for digital silence. */
export function rmsDbfs(samples: Float32Array): number {
  let sum = 0;
  for (const sample of samples) sum += sample * sample;
  return 10 * Math.log10(sum / Math.max(samples.length, 1));
}

/** 0..1 for the level bar: -60 dBFS and below is empty, 0 dBFS is full. */
export function meterLevel(db: number): number {
  return Math.min(1, Math.max(0, (db + 60) / 60));
}

export type LevelSummary = { peakDb: number; voicedSeconds: number };

export function isSilentRecording({ peakDb, voicedSeconds }: LevelSummary): boolean {
  return peakDb < SILENT_PEAK_DB || voicedSeconds < MIN_VOICED_SECONDS;
}

/** Samples the stream's loudness while recording; null where Web Audio is missing. */
function startMeter(stream: MediaStream, onLevel: (level: number) => void) {
  if (typeof AudioContext === "undefined") return null;
  const context = new AudioContext();
  const analyser = context.createAnalyser();
  analyser.fftSize = 2048;
  context.createMediaStreamSource(stream).connect(analyser);
  void context.resume();
  const samples = new Float32Array(analyser.fftSize);
  const summary: LevelSummary = { peakDb: -Infinity, voicedSeconds: 0 };
  let measured = false;
  let last = performance.now();
  const timer = window.setInterval(() => {
    const now = performance.now();
    // A suspended context reads zeros: that must not count as silence.
    if (context.state !== "running") {
      last = now;
      return;
    }
    measured = true;
    analyser.getFloatTimeDomainData(samples);
    const db = rmsDbfs(samples);
    summary.peakDb = Math.max(summary.peakDb, db);
    // Elapsed time rather than the interval: background tabs throttle timers.
    if (db > VOICED_DB) summary.voicedSeconds += (now - last) / 1000;
    last = now;
    onLevel(meterLevel(db));
  }, METER_INTERVAL_MS);
  return {
    /** null when nothing could be measured: then the recording is kept. */
    stop(): LevelSummary | null {
      window.clearInterval(timer);
      void context.close();
      return measured ? summary : null;
    },
  };
}

/** Click to start, click to stop; `onRecorded` gets the finished file unless it was silent. */
export function useRecorder(onRecorded: (file: File) => void) {
  const [recording, setRecording] = useState(false);
  const [seconds, setSeconds] = useState(0);
  const [level, setLevel] = useState(0);
  const [error, setError] = useState<RecorderError | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const discardRef = useRef(false);
  const onRecordedRef = useRef(onRecorded);
  useEffect(() => {
    onRecordedRef.current = onRecorded;
  });

  const start = useCallback(async () => {
    setError(null);
    const format =
      typeof MediaRecorder === "undefined"
        ? null
        : pickRecordingFormat((t) => MediaRecorder.isTypeSupported(t));
    if (!format || !navigator.mediaDevices?.getUserMedia) {
      setError("recording_unsupported");
      return;
    }
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      setError("microphone_denied");
      return;
    }
    const recorder = new MediaRecorder(stream, { mimeType: format.mimeType });
    const meter = startMeter(stream, setLevel);
    const chunks: Blob[] = [];
    const startedAt = Date.now();
    const timer = window.setInterval(() => {
      const elapsed = Math.floor((Date.now() - startedAt) / 1000);
      setSeconds(elapsed);
      if (elapsed >= MAX_RECORDING_SECONDS) recorder.stop();
    }, 250);
    recorder.ondataavailable = (event) => event.data.size > 0 && chunks.push(event.data);
    recorder.onstop = () => {
      window.clearInterval(timer);
      const levels = meter?.stop();
      stream.getTracks().forEach((track) => track.stop());
      recorderRef.current = null;
      setRecording(false);
      setSeconds(0);
      setLevel(0);
      if (discardRef.current || chunks.length === 0) return;
      if (levels && isSilentRecording(levels)) {
        setError("recording_silent");
        return;
      }
      const type = recorder.mimeType || format.mimeType;
      const stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-");
      onRecordedRef.current(
        new File(chunks, `voice-${stamp}.${format.extension}`, { type: type.split(";")[0] }),
      );
    };
    discardRef.current = false;
    recorderRef.current = recorder;
    recorder.start();
    setRecording(true);
  }, []);

  const stop = useCallback(() => recorderRef.current?.stop(), []);
  const cancel = useCallback(() => {
    discardRef.current = true;
    recorderRef.current?.stop();
  }, []);

  // Leaving the page mid-recording releases the microphone and keeps nothing.
  useEffect(() => cancel, [cancel]);

  return { recording, seconds, level, error, start, stop, cancel };
}
