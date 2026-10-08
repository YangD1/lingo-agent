"use client";

import { CheckIcon, XIcon } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";

import { useDescribeError } from "@/components/settings/use-describe-error";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ErrorText } from "@/components/ui/error-text";
import { answerQuestions, type Question, type QuizResult } from "@/lib/reading";
import { cn } from "@/lib/utils";

/**
 * Comprehension questions (Q43b): answer them all, then see which were right, the right
 * option and the sentence of the text that shows it. Only the first answers count toward
 * reading ability; once answered, the results stay.
 */
export function ReadingQuiz({
  sessionId,
  questions,
  initial,
  onAnswered,
}: {
  sessionId: string;
  questions: Question[];
  initial: QuizResult[] | null;
  onAnswered: (results: QuizResult[]) => void;
}) {
  const t = useTranslations("reading.quiz");
  const describe = useDescribeError();
  const [choices, setChoices] = useState<(number | null)[]>(() =>
    initial ? initial.map((r) => r.choice) : questions.map(() => null),
  );
  const [results, setResults] = useState<QuizResult[] | null>(initial);
  const [counted, setCounted] = useState<boolean | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    if (choices.some((c) => c === null) || busy) return;
    setBusy(true);
    setError(null);
    try {
      const answered = await answerQuestions(sessionId, choices as number[]);
      setResults(answered.results);
      setCounted(answered.counted);
      setChoices(answered.results.map((r) => r.choice));
      onAnswered(answered.results);
    } catch (e) {
      setError(describe(e));
    } finally {
      setBusy(false);
    }
  }

  const right = results?.filter((r) => r.correct).length ?? 0;

  return (
    <Card data-testid="reading-quiz">
      <CardHeader>
        <CardTitle>
          <h2>{t("title")}</h2>
        </CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-5 text-sm">
        {results && (
          <p className="font-medium" data-testid="reading-score">
            {t("score", { right, n: results.length })}
            {counted === false && <span className="ml-2 font-normal text-muted-foreground">{t("notCounted")}</span>}
            {counted === true && <span className="ml-2 font-normal text-muted-foreground">{t("counted")}</span>}
          </p>
        )}
        <ol className="flex flex-col gap-5">
          {questions.map((q, i) => {
            const result = results?.[i];
            return (
              <li key={i} className="flex flex-col gap-2" data-testid="reading-question">
                <fieldset className="flex flex-col gap-1.5">
                  <legend lang="en" className="mb-1.5 font-semibold">
                    {i + 1}. {q.question}
                  </legend>
                  {q.options.map((option, j) => {
                    const chosen = choices[i] === j;
                    const isAnswer = result?.answer === j;
                    return (
                      <label
                        key={j}
                        className={cn(
                          "flex cursor-pointer items-start gap-2 rounded-lg border px-3 py-2 transition-colors has-focus-visible:outline-2 has-focus-visible:outline-ring",
                          !result && "hover:bg-accent",
                          !result && chosen && "border-primary bg-brand-soft",
                          result && "cursor-default",
                          result && isAnswer && "border-success bg-[color-mix(in_oklab,var(--success)_10%,var(--card))]",
                          result && chosen && !isAnswer && "border-destructive",
                        )}
                      >
                        <input
                          type="radio"
                          name={`q${i}`}
                          className="mt-1 accent-primary"
                          checked={chosen}
                          disabled={result !== undefined}
                          onChange={() => setChoices((c) => c.map((v, k) => (k === i ? j : v)))}
                        />
                        <span lang="en" className="flex-1">
                          {option}
                        </span>
                        {result && isAnswer && <CheckIcon aria-label={t("right")} className="size-4 text-success" />}
                        {result && chosen && !isAnswer && (
                          <XIcon aria-label={t("wrong")} className="size-4 text-destructive" />
                        )}
                      </label>
                    );
                  })}
                </fieldset>
                {result && (
                  <p className="text-xs text-muted-foreground">
                    {t("evidence")} <q lang="en">{result.evidence}</q>
                  </p>
                )}
              </li>
            );
          })}
        </ol>
        {error && <ErrorText>{error}</ErrorText>}
        {!results && (
          <Button
            className="self-start"
            disabled={busy || choices.some((c) => c === null)}
            onClick={() => void submit()}
            data-testid="reading-submit"
          >
            {busy ? t("submitting") : t("submit")}
          </Button>
        )}
      </CardContent>
    </Card>
  );
}
