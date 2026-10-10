import { apiFetch, api } from "@/lib/api";
import { type ShadowingMode, speechSegments, useServerSpeech } from "@/lib/speech";

export type { ShadowingMode } from "@/lib/speech";

/** Where the sentence was read from (ADR 0028 §6). */
export type ShadowingSource = "chat" | "reading" | "vocab" | "speaking";
export type ShadowingLanguage = "en-US" | "en-GB";

/** Pronunciation assessment and the short-audio API take at most this much text. */
export const MAX_SHADOWING_CHARS = 600;

export type PhonemeScore = { phoneme: string | null; accuracy: number };

/**
 * One word of the sentence. Assessed: `accuracy` 0–100 (null when left out) and phonemes;
 * Azure's errors are "None" / "Mispronunciation" / "Omission" / "Insertion" and the rest.
 * Rough: no accuracy; `error` is none / omission / substitution (with `heard`) / insertion.
 */
export type ShadowingWord = {
  word: string;
  accuracy?: number | null;
  error: string;
  phonemes?: PhonemeScore[];
  heard?: string | null;
};

export type ShadowingScores = {
  overall: number;
  accuracy: number;
  fluency: number;
  completeness: number;
  prosody?: number | null;
};

export type ShadowingResult = {
  id: string;
  source: ShadowingSource;
  source_id: string | null;
  reference_text: string;
  language: ShadowingLanguage;
  mode: ShadowingMode;
  /** Why a rough result stands in: "not_configured" or "failed". */
  fallback_reason: string | null;
  scores: ShadowingScores | null;
  words: ShadowingWord[];
  recognized_text: string;
  audio_seconds: number;
  /** It moved the speaking ability. */
  counted: boolean;
  created_at: string;
  /** Words of the sentence the learner says wrong now (assessment only). */
  mispronounced: string[];
};

export type ShadowingPage = { items: ShadowingResult[]; next_before: string | null };

export async function submitShadowing(
  file: File,
  sentence: string,
  language: ShadowingLanguage,
  source: ShadowingSource,
  sourceId?: string,
  signal?: AbortSignal,
): Promise<ShadowingResult> {
  const form = new FormData();
  form.append("file", file);
  form.append("reference_text", sentence);
  form.append("language", language);
  form.append("source", source);
  if (sourceId) form.append("source_id", sourceId);
  const response = await apiFetch("/speech/shadowing", { method: "POST", body: form, signal });
  return (await response.json()) as ShadowingResult;
}

export const fetchShadowing = (before?: string, limit = 20) =>
  api<ShadowingPage>(
    `/speech/shadowing?limit=${limit}${before ? `&before=${encodeURIComponent(before)}` : ""}`,
  );

export const deleteShadowing = (id: string) =>
  api<void>(`/speech/shadowing/${id}`, { method: "DELETE" });

export const clearShadowing = () =>
  api<{ deleted: number }>("/speech/shadowing", { method: "DELETE" });

/** How this tenant scores shadowing; null until known, or when nothing can score it. */
export function useShadowingMode(): ShadowingMode | null {
  return useServerSpeech().shadowing;
}

/**
 * The English sentences of `text` a learner can read back: the English runs of a mixed
 * reply cut at sentence ends, of at least two words (not a lone "OK" or "B1") and at most
 * 600 characters (longer is too long for one reading).
 */
export function shadowingSentences(text: string): string[] {
  const sentences = speechSegments(text)
    .filter((segment) => segment.lang === "en-US")
    .flatMap((segment) => segment.text.split(/(?<=[.?!])\s+|\n+/))
    .map((sentence) => sentence.trim().replace(/^[-*•>\d.)\s]+(?=[A-Za-z"'])/, ""))
    .filter(
      (sentence) =>
        (sentence.match(/[A-Za-z]+/g)?.length ?? 0) >= 2 &&
        sentence.length <= MAX_SHADOWING_CHARS,
    );
  return [...new Set(sentences)];
}

/** How well a word was said, for its colour: assessment by accuracy, rough by error. */
export type WordGrade = "good" | "fair" | "poor" | "missed" | "extra";

// Azure's own bands: 80+ is shown as fine, under 60 as mispronounced (the threshold the
// backend marks words with, rules.yaml pronunciation.word_threshold).
export const GOOD_ACCURACY = 80;
export const POOR_ACCURACY = 60;

export function gradeWord(word: ShadowingWord): WordGrade {
  const error = word.error.toLowerCase();
  if (error === "omission") return "missed";
  if (error === "insertion") return "extra";
  if (error === "substitution") return "poor";
  if (word.accuracy == null) return error === "none" ? "good" : "poor";
  if (word.accuracy >= GOOD_ACCURACY && error === "none") return "good";
  return word.accuracy >= POOR_ACCURACY ? "fair" : "poor";
}
