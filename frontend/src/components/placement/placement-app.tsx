"use client";

import { useTranslations } from "next-intl";
import { useCallback, useEffect, useRef, useState } from "react";

import { useDescribeError } from "@/components/settings/use-describe-error";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ApiError } from "@/lib/api";
import { isShortcut } from "@/lib/keyboard";
import {
  type Answer,
  answerPlacement,
  fetchLatestPlacement,
  fetchPlacement,
  type Placement,
  type Question,
  startPlacement,
} from "@/lib/placement";

import { PlacementResult } from "./placement-result";

type State =
  | { kind: "loading" }
  | { kind: "intro" }
  | { kind: "question"; placement: Placement; question: Question }
  | { kind: "done"; placement: Placement };

function stateOf(placement: Placement | null): State {
  if (placement?.status === "done") return { kind: "done", placement };
  if (placement?.status === "in_progress" && placement.question)
    return { kind: "question", placement, question: placement.question };
  return { kind: "intro" };
}

/**
 * The placement test (P1 plan §6.3): a vocabulary part (do you know this word? some are
 * made up), then multiple-choice grammar; the result sets the learner's level. A test
 * left halfway is picked up where it stopped, here or on another device.
 */
export function PlacementApp() {
  const t = useTranslations("placement");
  const describe = useDescribeError();
  const [state, setState] = useState<State>({ kind: "loading" });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // A second key press or click lands before React re-renders with `busy`.
  const sending = useRef(false);

  useEffect(() => {
    fetchLatestPlacement().then(
      (latest) => setState(stateOf(latest)),
      (e: unknown) => {
        setState({ kind: "intro" });
        setError(describe(e));
      },
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps -- describe is stable enough
  }, []);

  async function start(restart: boolean) {
    setBusy(true);
    setError(null);
    try {
      setState(stateOf(await startPlacement(restart)));
    } catch (e) {
      setError(describe(e));
    } finally {
      setBusy(false);
    }
  }

  const answer = useCallback(
    async (reply: Answer) => {
      if (state.kind !== "question" || sending.current) return;
      const { placement, question } = state;
      sending.current = true;
      setBusy(true);
      setError(null);
      try {
        setState(stateOf(await answerPlacement(placement.id, question.id, reply)));
      } catch (e) {
        setError(describe(e));
        if (e instanceof ApiError && e.code === "stale_question") {
          // Answered elsewhere: show whatever the test is at now.
          setState(stateOf(await fetchPlacement(placement.id).catch(() => null)));
        } else if (e instanceof ApiError && e.code === "placement_not_in_progress") {
          setState({ kind: "intro" });
        }
      } finally {
        sending.current = false;
        setBusy(false);
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps -- describe is stable enough
    [state],
  );

  useEffect(() => {
    if (state.kind !== "question") return;
    const { stage, options } = state.question;
    function onKey(event: KeyboardEvent) {
      if (!isShortcut(event)) return;
      const key = event.key.toLowerCase();
      let reply: Answer | null = null;
      if (stage === "vocab" && (key === "y" || key === "n")) reply = { yes: key === "y" };
      const choice = Number(key) - 1;
      if (stage === "grammar" && options && Number.isInteger(choice) && options[choice])
        reply = { choice };
      if (reply) {
        event.preventDefault();
        void answer(reply);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [state, answer]);

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="mx-auto flex max-w-2xl flex-col gap-4 p-4 md:p-8">
        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}
        {state.kind === "intro" && (
          <Card data-testid="placement-intro">
            <CardHeader>
              <CardTitle>{t("title")}</CardTitle>
              <CardDescription>{t("description")}</CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-4 text-sm">
              <ol className="flex list-decimal flex-col gap-2 pl-5">
                <li>{t("intro.vocab")}</li>
                <li>{t("intro.grammar")}</li>
              </ol>
              <p className="text-muted-foreground">{t("intro.notes")}</p>
              <div>
                <Button disabled={busy} onClick={() => void start(false)}>
                  {t("intro.start")}
                </Button>
              </div>
            </CardContent>
          </Card>
        )}
        {state.kind === "question" && (
          <QuestionCard question={state.question} busy={busy} onAnswer={answer} />
        )}
        {state.kind === "done" && state.placement.result && (
          <PlacementResult
            result={state.placement.result}
            finishedAt={state.placement.finished_at}
            busy={busy}
            onRetest={() => void start(true)}
          />
        )}
      </div>
    </div>
  );
}

function QuestionCard({
  question,
  busy,
  onAnswer,
}: {
  question: Question;
  busy: boolean;
  onAnswer: (answer: Answer) => Promise<void>;
}) {
  const t = useTranslations("placement.question");
  const vocab = question.stage === "vocab";
  return (
    <Card data-testid="placement-question">
      <CardHeader>
        <CardDescription data-testid="placement-progress">
          {t(vocab ? "vocabProgress" : "grammarProgress", {
            n: question.index + 1,
            total: question.total,
          })}
        </CardDescription>
        <CardTitle>{t(vocab ? "vocabPrompt" : "grammarPrompt")}</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-6">
        {vocab ? (
          <>
            <p className="text-center text-4xl font-semibold tracking-wide" lang="en">
              {question.word}
            </p>
            <div className="grid grid-cols-2 gap-3">
              <Button
                variant="outline"
                size="lg"
                disabled={busy}
                onClick={() => void onAnswer({ yes: false })}
              >
                {t("no")}
              </Button>
              <Button size="lg" disabled={busy} onClick={() => void onAnswer({ yes: true })}>
                {t("yes")}
              </Button>
            </div>
            <p className="text-center text-xs text-muted-foreground">{t("vocabHint")}</p>
          </>
        ) : (
          <>
            <p className="text-lg" lang="en" data-testid="placement-stem">
              {question.stem}
            </p>
            <ol className="flex flex-col gap-2">
              {(question.options ?? []).map((option, i) => (
                <li key={option}>
                  <Button
                    variant="outline"
                    className="h-auto w-full justify-start py-2 text-left whitespace-normal"
                    disabled={busy}
                    onClick={() => void onAnswer({ choice: i })}
                  >
                    <span className="mr-2 text-muted-foreground">{i + 1}.</span>
                    <span lang="en">{option}</span>
                  </Button>
                </li>
              ))}
            </ol>
            <p className="text-center text-xs text-muted-foreground">{t("grammarHint")}</p>
          </>
        )}
      </CardContent>
    </Card>
  );
}
