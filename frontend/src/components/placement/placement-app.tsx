"use client";

import { BookOpen, ListChecks } from "lucide-react";
import { useTranslations } from "next-intl";
import { Fragment, type ReactNode, useCallback, useEffect, useRef, useState } from "react";

import { CatLoading } from "@/components/brand/lingo-cat";
import { useDescribeError } from "@/components/settings/use-describe-error";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ProgressBar } from "@/components/ui/progress";
import { ErrorText } from "@/components/ui/error-text";
import { ApiError } from "@/lib/api";
import { isShortcut } from "@/lib/keyboard";
import { EmptyState } from "@/components/ui/empty-state";
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
  const tCat = useTranslations("cat");
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
      <div className="mx-auto flex max-w-2xl flex-col gap-3.5 p-4 md:gap-4 md:px-10 md:py-8">
        {error &&
          (state.kind !== "loading" ? (
            <ErrorText>{error}</ErrorText>
          ) : (
            // Nothing loaded: the whole area failed, so the big oops cat.
            <EmptyState tone="error" title={error} />
          ))}
        {state.kind === "loading" && !error && <CatLoading label={tCat("loader")} />}
        {state.kind === "intro" && (
          <Card data-testid="placement-intro">
            <CardHeader>
              <CardTitle>
                <h1>{t("title")}</h1>
              </CardTitle>
              <CardDescription>{t("description")}</CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-4 text-sm">
              <p>{t("intro.lead")}</p>
              <ol className="grid gap-3 sm:grid-cols-2">
                {PARTS.map(({ key, icon: Icon }) => (
                  <li key={key} className="flex flex-col gap-2 rounded-lg border bg-muted/50 p-4">
                    <div className="flex items-center gap-3">
                      <span className="flex size-8 shrink-0 items-center justify-center rounded-md bg-accent text-accent-foreground">
                        <Icon aria-hidden className="size-4" />
                      </span>
                      <div className="flex flex-col">
                        <span className="font-semibold">{t(`intro.${key}Title`)}</span>
                        <span className="text-xs text-muted-foreground">{t(`intro.${key}Meta`)}</span>
                      </div>
                    </div>
                    <p className="text-[13px] text-muted-foreground">{t(`intro.${key}`)}</p>
                  </li>
                ))}
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
  const n = question.index + 1;
  return (
    <Card data-testid="placement-question">
      <CardHeader className="gap-2.5">
        <div className="flex items-baseline justify-between gap-3 text-xs text-muted-foreground">
          <span>{t(vocab ? "vocabStage" : "grammarStage")}</span>
          <span className="font-mono tabular-nums" data-testid="placement-progress">
            {t(vocab ? "vocabCount" : "grammarCount", { n, total: question.total })}
          </span>
        </div>
        <ProgressBar value={Math.min(1, n / question.total)} thin />
      </CardHeader>
      <CardContent className="flex flex-col gap-5">
        {vocab ? (
          <>
            <div className="flex flex-col items-center gap-3 py-4">
              <p className="text-[13px] text-muted-foreground">{t("vocabPrompt")}</p>
              <p className="text-[40px] leading-tight font-bold tracking-tight md:text-5xl" lang="en">
                {question.word}
              </p>
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <Button
                variant="outline"
                size="lg"
                className="h-12 md:h-12"
                disabled={busy}
                onClick={() => void onAnswer({ yes: false })}
              >
                {t("no")}
              </Button>
              <Button
                variant="outline"
                size="lg"
                className="h-12 md:h-12"
                disabled={busy}
                onClick={() => void onAnswer({ yes: true })}
              >
                {t("yes")}
              </Button>
            </div>
            <p className="text-center text-xs text-muted-foreground max-md:hidden">
              {t.rich("vocabKeys", { k: kbd })}
            </p>
          </>
        ) : (
          <>
            <div className="flex flex-col gap-2">
              <p className="text-[13px] text-muted-foreground">{t("grammarPrompt")}</p>
              <p className="text-xl leading-relaxed md:text-[22px]" lang="en" data-testid="placement-stem">
                <Stem text={question.stem ?? ""} blank={t("blank")} />
              </p>
            </div>
            <ol className="flex flex-col gap-2">
              {(question.options ?? []).map((option, i) => (
                <li key={option}>
                  <Button
                    variant="outline"
                    className="h-auto w-full justify-start gap-3 px-4 py-3 text-left text-[15px] whitespace-normal md:h-auto"
                    disabled={busy}
                    onClick={() => void onAnswer({ choice: i })}
                  >
                    <span className="font-mono text-muted-foreground">{i + 1}.</span>
                    <span lang="en">{option}</span>
                  </Button>
                </li>
              ))}
            </ol>
            <p className="text-center text-xs text-muted-foreground max-md:hidden">
              {t.rich("grammarKeys", { k: kbd })}
            </p>
          </>
        )}
      </CardContent>
    </Card>
  );
}

const PARTS = [
  { key: "vocab", icon: BookOpen },
  { key: "grammar", icon: ListChecks },
] as const;

const kbd = (chunks: ReactNode) => (
  <kbd className="mx-0.5 inline-flex h-5 min-w-5 items-center justify-center rounded-[5px] border bg-card px-1 font-mono text-[11px]">
    {chunks}
  </kbd>
);

/** The stem with its blank (a run of underscores) drawn as a line. */
function Stem({ text, blank }: { text: string; blank: string }) {
  const parts = text.split(/_{2,}/);
  return parts.map((part, i) => (
    <Fragment key={i}>
      {i > 0 && (
        <span className="mx-1 inline-block w-24 border-b-2 border-foreground align-baseline">
          <span className="sr-only">{blank}</span>
        </span>
      )}
      {part}
    </Fragment>
  ));
}
