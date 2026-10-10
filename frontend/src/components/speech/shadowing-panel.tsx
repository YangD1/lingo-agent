"use client";

import { Info, Mic, Square, Volume2, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useRef, useState } from "react";

import { AiBadge } from "@/components/ai-badge";
import { LingoCat } from "@/components/brand/lingo-cat";
import { LevelMeter } from "@/components/chat/composer";
import { useDescribeError } from "@/components/settings/use-describe-error";
import { Button } from "@/components/ui/button";
import { Callout } from "@/components/ui/callout";
import { ApiError, isAbortError } from "@/lib/api";
import {
  gradeWord,
  POOR_ACCURACY,
  GOOD_ACCURACY,
  type ShadowingResult,
  type ShadowingSource,
  type ShadowingWord,
  submitShadowing,
  useShadowingMode,
  type WordGrade,
  wordIssue,
} from "@/lib/shadowing";
import { speakSegments, stopSpeaking, useCanSpeak, useSpeaking, useSpeechSettings } from "@/lib/speech";
import { cn } from "@/lib/utils";
import { addMine } from "@/lib/vocab";

import { MAX_SHADOWING_SECONDS, useWavRecorder } from "./use-wav-recorder";

// Shown in the panel's own words; anything else (offline, signed out) as everywhere else.
const SHADOWING_ERRORS = new Set([
  "invalid_audio",
  "no_speech",
  "not_configured",
  "unavailable",
  "recording_too_large",
]);
const DEMO_OWNER = "shadowing";

const WORD_STYLE: Record<WordGrade, string> = {
  good: "text-success",
  fair: "text-warning",
  poor: "text-destructive underline decoration-wavy decoration-1 underline-offset-4",
  missed: "text-muted-foreground line-through",
  extra: "text-muted-foreground italic",
};

const scoreTone = (score: number) =>
  score >= GOOD_ACCURACY ? "text-success" : score >= POOR_ACCURACY ? "text-warning" : "text-destructive";

/**
 * Shadowing (ADR 0028 §5): listen to the sentence, read it back, see how it went. Opens in
 * place under the text it reads from; with several sentences the learner picks one (Q57a,
 * Q57b). Rendered only while the tenant can score shadowing (`useShadowingMode`).
 */
export function ShadowingPanel({
  sentences,
  source,
  sourceId,
  onClose,
  className,
}: {
  sentences: string[];
  source: ShadowingSource;
  sourceId?: string;
  onClose: () => void;
  className?: string;
}) {
  const t = useTranslations("speech.shadowing");
  const describe = useDescribeError();
  const mode = useShadowingMode();
  const canDemo = useCanSpeak();
  const demoPlaying = useSpeaking(DEMO_OWNER);
  const [settings] = useSpeechSettings();
  const [index, setIndex] = useState(0);
  const [scoring, setScoring] = useState(false);
  const [result, setResult] = useState<ShadowingResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const requestRef = useRef<AbortController | null>(null);
  const sentence = sentences[Math.min(index, sentences.length - 1)] ?? "";

  const recorder = useWavRecorder(async (file) => {
    const request = new AbortController();
    requestRef.current = request;
    setScoring(true);
    try {
      const scored = await submitShadowing(
        file,
        sentence,
        settings.accent,
        source,
        sourceId,
        request.signal,
      );
      if (!request.signal.aborted) setResult(scored);
    } catch (e) {
      if (isAbortError(e)) return;
      setError(
        e instanceof ApiError && SHADOWING_ERRORS.has(e.code)
          ? t(`errors.${e.code as "no_speech"}`)
          : describe(e),
      );
    } finally {
      if (requestRef.current === request) {
        requestRef.current = null;
        setScoring(false);
      }
    }
  });

  // Closing or leaving drops the reading on its way and stops the example.
  useEffect(
    () => () => {
      requestRef.current?.abort();
      stopSpeaking();
    },
    [],
  );

  const choose = (next: number) => {
    if (recorder.recording) recorder.cancel();
    requestRef.current?.abort();
    setIndex(next);
    setResult(null);
    setError(null);
  };

  const demo = () => {
    if (demoPlaying) return stopSpeaking();
    speakSegments(DEMO_OWNER, [{ text: sentence, lang: "en-US" }]);
  };

  const record = () => {
    if (recorder.recording) return recorder.stop();
    // The example must not end up in the recording.
    stopSpeaking();
    setError(null);
    setResult(null);
    void recorder.start();
  };

  if (!mode || !sentence) return null;
  const recorderError = recorder.error ? t(`errors.${recorder.error}`) : null;

  return (
    <section
      data-testid="shadowing-panel"
      aria-label={t("title")}
      className={cn("flex flex-col gap-3 rounded-xl border bg-card p-3 text-sm", className)}
    >
      <header className="flex items-center gap-1.5">
        <Mic aria-hidden className="size-4 text-muted-foreground" />
        <h3 className="font-medium">{t("title")}</h3>
        <AiBadge feature={mode === "assessment" ? "shadowing" : "shadowing_rough"} />
        <Button
          size="icon-xs"
          variant="ghost"
          className="ml-auto"
          aria-label={t("close")}
          onClick={onClose}
        >
          <X />
        </Button>
      </header>

      {sentences.length > 1 && (
        <ol className="flex flex-col gap-1" aria-label={t("pick")} data-testid="shadowing-sentences">
          {sentences.map((s, i) => (
            <li key={s}>
              <button
                type="button"
                aria-pressed={i === index}
                onClick={() => choose(i)}
                className={cn(
                  "w-full rounded-md px-2 py-1 text-left text-muted-foreground hover:bg-muted",
                  i === index && "bg-brand-soft text-foreground",
                )}
              >
                {s}
              </button>
            </li>
          ))}
        </ol>
      )}

      {result ? (
        <ResultView key={result.id} result={result} />
      ) : (
        <p className="text-base leading-relaxed" data-testid="shadowing-sentence">
          {sentence}
        </p>
      )}

      <div className="flex flex-wrap items-center gap-2">
        {canDemo && (
          <Button size="sm" variant="outline" onClick={demo} disabled={recorder.recording}>
            {demoPlaying ? <Square /> : <Volume2 />}
            {demoPlaying ? t("stopDemo") : t("demo")}
          </Button>
        )}
        <Button
          size="sm"
          variant={recorder.recording ? "destructive" : "default"}
          onClick={record}
          disabled={scoring}
          data-testid="shadowing-record"
        >
          {recorder.recording ? <Square /> : <Mic />}
          {recorder.recording ? t("stop") : result ? t("again") : t("record")}
        </Button>
        {recorder.recording && (
          <>
            <LevelMeter level={recorder.level} />
            <span className="text-xs tabular-nums text-muted-foreground">
              {t("seconds", { seconds: recorder.seconds, max: MAX_SHADOWING_SECONDS })}
            </span>
          </>
        )}
        {result && index < sentences.length - 1 && (
          <Button size="sm" variant="ghost" onClick={() => choose(index + 1)}>
            {t("next")}
          </Button>
        )}
      </div>

      {scoring && (
        <p className="flex items-center gap-1.5 text-xs text-muted-foreground" role="status">
          <LingoCat mood="ai" size={16} label="" />
          {mode === "assessment" ? t("scoring") : t("comparing")}
        </p>
      )}
      {(error ?? recorderError) && (
        <p role="alert" className="text-xs text-destructive">
          {error ?? recorderError}
        </p>
      )}
      {!result && !recorder.recording && !scoring && (
        <p className="text-xs text-muted-foreground">
          {mode === "assessment" ? t("hint") : t("hintRough")}
        </p>
      )}
    </section>
  );
}

function ResultView({ result }: { result: ShadowingResult }) {
  const t = useTranslations("speech.shadowing");
  const [open, setOpen] = useState<number | null>(null);
  const assessed = result.mode === "assessment" && result.scores;
  const heard = result.words.filter((w) => gradeWord(w) !== "extra");
  const matched = heard.filter((w) => gradeWord(w) === "good").length;
  const word = open === null ? null : result.words[open];

  return (
    <div className="flex flex-col gap-3" data-testid="shadowing-result" data-mode={result.mode}>
      {assessed ? (
        <Scores scores={result.scores!} />
      ) : (
        <Callout icon={<Info />} data-testid="shadowing-rough">
          <span>
            {result.fallback_reason === "failed" ? t("roughFailed") : t("rough")}{" "}
            {t("matched", { matched, total: heard.length })}
          </span>
        </Callout>
      )}

      <p className="flex flex-wrap gap-x-1.5 gap-y-1 text-base leading-relaxed" data-testid="shadowing-words">
        {result.words.map((w, i) => (
          <button
            key={i}
            type="button"
            aria-expanded={open === i}
            data-grade={gradeWord(w)}
            onClick={() => setOpen(open === i ? null : i)}
            className={cn(
              "rounded px-0.5 hover:bg-muted",
              WORD_STYLE[gradeWord(w)],
              open === i && "bg-muted",
            )}
          >
            {w.word}
          </button>
        ))}
      </p>
      {word && <WordDetail word={word} language={result.language} />}
      <p className="text-xs text-muted-foreground">{t("legend")}</p>

      {assessed && !result.counted && (
        <p className="text-xs text-muted-foreground">{t("notCounted")}</p>
      )}
      {result.mispronounced.length > 0 && <AddWords words={result.mispronounced} />}
    </div>
  );
}

function Scores({ scores }: { scores: NonNullable<ShadowingResult["scores"]> }) {
  const t = useTranslations("speech.shadowing");
  const rows: [string, number | null | undefined][] = [
    [t("accuracy"), scores.accuracy],
    [t("fluency"), scores.fluency],
    [t("completeness"), scores.completeness],
    [t("prosody"), scores.prosody],
  ];
  return (
    <div className="flex items-center gap-4" data-testid="shadowing-scores">
      <ScoreRing score={scores.overall} label={t("overall")} />
      <dl className="grid grid-cols-[auto_auto] gap-x-3 gap-y-0.5 text-xs">
        {rows
          .filter((row): row is [string, number] => row[1] != null)
          .map(([label, value]) => (
            <div key={label} className="contents">
              <dt className="text-muted-foreground">{label}</dt>
              <dd className={cn("font-medium tabular-nums", scoreTone(value))}>
                {Math.round(value)}
              </dd>
            </div>
          ))}
      </dl>
    </div>
  );
}

function ScoreRing({ score, label }: { score: number; label: string }) {
  const radius = 22;
  const circumference = 2 * Math.PI * radius;
  const value = Math.round(score);
  return (
    <div className="relative size-14 shrink-0" role="img" aria-label={`${label} ${value}`}>
      <svg viewBox="0 0 56 56" className="size-full -rotate-90">
        <circle cx="28" cy="28" r={radius} fill="none" strokeWidth="5" className="stroke-muted" />
        <circle
          cx="28"
          cy="28"
          r={radius}
          fill="none"
          strokeWidth="5"
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={circumference * (1 - Math.min(100, Math.max(0, score)) / 100)}
          className={cn("stroke-current", scoreTone(score))}
        />
      </svg>
      <span
        className="absolute inset-0 flex items-center justify-center text-base font-semibold tabular-nums"
        data-testid="shadowing-overall"
      >
        {value}
      </span>
    </div>
  );
}

function WordDetail({ word, language }: { word: ShadowingWord; language: string }) {
  const t = useTranslations("speech.shadowing");
  const grade = gradeWord(word);
  const error = wordIssue(word);
  const phonemes = word.phonemes ?? [];
  const named = phonemes.some((p) => p.phoneme);
  return (
    <div className="rounded-md bg-muted px-2.5 py-2 text-xs" data-testid="shadowing-word-detail">
      <p>
        <span className="font-medium">{word.word}</span>{" "}
        {error === "omission"
          ? t("omitted")
          : error === "insertion"
            ? t("inserted")
            : error === "substitution"
              ? t("heardAs", { heard: word.heard ?? "" })
              : word.accuracy != null
                ? t("wordAccuracy", { score: Math.round(word.accuracy) })
                : grade === "good"
                  ? t("heardRight")
                  : null}
      </p>
      {named && (
        <ul className="mt-1.5 flex flex-wrap gap-1.5" aria-label={t("phonemes")}>
          {phonemes.map((p, i) => (
            <li key={i} className={cn("rounded bg-card px-1.5 py-0.5 font-mono", scoreTone(p.accuracy))}>
              /{p.phoneme ?? "?"}/ {Math.round(p.accuracy)}
            </li>
          ))}
        </ul>
      )}
      {!named && phonemes.length > 0 && language !== "en-US" && (
        <p className="mt-1 text-muted-foreground">{t("noPhonemeNames")}</p>
      )}
    </div>
  );
}

function AddWords({ words }: { words: string[] }) {
  const t = useTranslations("speech.shadowing");
  const describe = useDescribeError();
  const [state, setState] = useState<Record<string, "busy" | "added" | "onList">>({});
  const [error, setError] = useState<string | null>(null);

  const add = async (word: string) => {
    setState((s) => ({ ...s, [word]: "busy" }));
    setError(null);
    try {
      const result = await addMine(word);
      setState((s) => ({ ...s, [word]: result.added ? "added" : "onList" }));
    } catch (e) {
      setState((s) => {
        const rest = { ...s };
        delete rest[word];
        return rest;
      });
      setError(describe(e));
    }
  };

  return (
    <div className="flex flex-col gap-1.5" data-testid="shadowing-mispronounced">
      <p className="text-xs text-muted-foreground">{t("mispronounced")}</p>
      <ul className="flex flex-wrap gap-1.5">
        {words.map((word) => (
          <li key={word} className="flex items-center gap-1 rounded-md border px-2 py-0.5">
            <span className="font-medium">{word}</span>
            {state[word] === "added" || state[word] === "onList" ? (
              <span className="text-xs text-muted-foreground">
                {state[word] === "added" ? t("added") : t("onList")}
              </span>
            ) : (
              <Button
                size="xs"
                variant="link"
                disabled={state[word] === "busy"}
                onClick={() => add(word)}
              >
                {t("add")}
              </Button>
            )}
          </li>
        ))}
      </ul>
      {error && (
        <p role="alert" className="text-xs text-destructive">
          {error}
        </p>
      )}
    </div>
  );
}
