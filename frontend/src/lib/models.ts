import type { DiscoveredModel } from "./types";

/** Model ids that can go in a chat dropdown (the backend's name-based guess, ADR 0007 §1). */
export function chatModelIds(models: DiscoveredModel[]): string[] {
  return models.filter((m) => m.category === "chat").map((m) => m.id);
}

// Transcription models by name; the backend files them under "other" with TTS etc.
const SPEECH_TO_TEXT = /whisper|transcri|asr|sensevoice|paraformer/i;

/** Model ids that can go in a speech-to-text dropdown. */
export function speechModelIds(models: DiscoveredModel[]): string[] {
  return models.filter((m) => m.category !== "embedding" && SPEECH_TO_TEXT.test(m.id)).map((m) => m.id);
}

/** The model part of "<connection>:<model>" refs, in order. */
export function modelsOfRefs(refs: string[]): string[] {
  return refs.flatMap((ref) => {
    const i = ref.indexOf(":");
    return i > 0 ? [ref.slice(i + 1)] : [];
  });
}

/**
 * The model to preselect as a connection's default (ADR 0007 §2): the first `preferred`
 * one the connection actually serves, else its first chat model, else "".
 */
export function recommendModel(available: string[], preferred: string[]): string {
  return preferred.find((m) => available.includes(m)) ?? available[0] ?? "";
}
