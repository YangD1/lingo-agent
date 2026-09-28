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

export type RecorderError = "microphone_denied" | "recording_unsupported";

/** Click to start, click to stop; `onRecorded` gets the finished file. */
export function useRecorder(onRecorded: (file: File) => void) {
  const [recording, setRecording] = useState(false);
  const [seconds, setSeconds] = useState(0);
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
      stream.getTracks().forEach((track) => track.stop());
      recorderRef.current = null;
      setRecording(false);
      setSeconds(0);
      if (discardRef.current || chunks.length === 0) return;
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

  return { recording, seconds, error, start, stop, cancel };
}
