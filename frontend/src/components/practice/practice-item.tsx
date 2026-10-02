"use client";

import { CircleCheck, CircleX, Flag } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { Fragment, type ReactNode, useEffect, useRef, useState } from "react";

import { AiBadge } from "@/components/ai-badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { ErrorText } from "@/components/ui/error-text";
import { InlineConfirm } from "@/components/ui/inline-confirm";
import { Input } from "@/components/ui/input";
import { ProgressBar } from "@/components/ui/progress";
import { CefrTag, Tag } from "@/components/ui/tag";
import { Textarea } from "@/components/ui/textarea";
import { isShortcut } from "@/lib/keyboard";
import { kcName } from "@/lib/learner";
import { type Item, keyText, type Reply, replyText } from "@/lib/practice";
import { cn } from "@/lib/utils";

/** Formats whose answer a model grades (ADR 0021 §6): find_fix only when the fix is new. */
const MODEL_GRADED = new Set(["find_fix", "transform", "translate", "rewrite_own"]);

/**
 * One practice item on its own screen (P2 plan §3.7): the question and its answer
 * control, then, once answered, right or wrong with the key, the explanation and any
 * other mistakes. Keys: 1–4 pick an option, 1–6 a piece of a find-the-error sentence,
 * Enter goes on once answered.
 */
export function PracticeItem({
  item,
  index,
  total,
  busy,
  error,
  onAnswer,
  onReport,
  onNext,
}: {
  item: Item;
  /** 0-based among the set's items. */
  index: number;
  total: number;
  busy: boolean;
  error: string | null;
  onAnswer: (reply: Reply, latencyMs: number) => void;
  onReport: () => void;
  /** Shown once answered or reported. */
  onNext: (() => void) | null;
}) {
  const t = useTranslations("practice.item");
  const locale = useLocale();
  const shownAt = useRef(0);
  const [text, setText] = useState("");
  const [segment, setSegment] = useState<number | null>(null);
  const answered = item.result !== null || item.status === "reported";

  // The parent keys this component by item, so the answer state starts empty per item.
  useEffect(() => {
    shownAt.current = performance.now();
  }, []);

  const submit = (reply: Reply) => {
    if (busy || answered) return;
    onAnswer(reply, performance.now() - shownAt.current);
  };

  function pickSegment(i: number) {
    if (answered) return;
    setSegment(i);
    setText(item.content.segments?.[i]?.trim() ?? "");
  }

  function submitFix() {
    const pieces = item.content.segments;
    if (segment === null || !pieces || !text.trim()) return;
    // Keep the piece's own spacing, so the sentence still reads when joined.
    const piece = pieces[segment];
    const lead = piece.match(/^\s*/)?.[0] ?? "";
    const trail = piece.match(/\s*$/)?.[0] ?? "";
    submit({ segment, fix: `${lead}${text.trim()}${trail}` });
  }

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key === "Enter" && answered && onNext && !event.isComposing) {
        const target = event.target as HTMLElement | null;
        if (target?.closest("button, a")) return; // the focused control handles it
        event.preventDefault();
        onNext();
        return;
      }
      if (!isShortcut(event) || answered) return;
      const n = Number(event.key) - 1;
      if (!Number.isInteger(n) || n < 0) return;
      if (item.format === "choice4" && item.content.options?.[n] !== undefined) {
        event.preventDefault();
        submit({ choice: item.content.options[n] });
      } else if (item.format === "find_fix" && item.content.segments?.[n] !== undefined) {
        event.preventDefault();
        pickSegment(n);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  const reply = item.result?.response;
  return (
    <Card data-testid="practice-item" data-format={item.format}>
      <CardHeader className="gap-2.5">
        <div className="flex items-center justify-between gap-3 text-xs text-muted-foreground">
          <span className="flex min-w-0 items-center gap-2">
            <span className="truncate">{kcName(item.kc, locale)}</span>
            {item.kc.cefr && <CefrTag level={item.kc.cefr} />}
            {item.from_bank && <Tag variant="outline">{t("fromBank")}</Tag>}
          </span>
          <span className="font-mono tabular-nums" data-testid="practice-progress">
            {t("count", { n: index + 1, total })}
          </span>
        </div>
        <ProgressBar value={Math.min(1, (index + (answered ? 1 : 0)) / total)} thin />
      </CardHeader>
      <CardContent className="flex flex-col gap-5">
        <Question item={item} segment={segment} answered={answered} onPick={pickSegment} />

        {!answered && item.format === "choice4" && (
          <>
            <ol className="flex flex-col gap-2">
              {(item.content.options ?? []).map((option, i) => (
                <li key={option}>
                  <Button
                    variant="outline"
                    className="h-auto w-full justify-start gap-3 px-4 py-3 text-left text-[15px] whitespace-normal md:h-auto"
                    disabled={busy}
                    onClick={() => submit({ choice: option })}
                  >
                    <span className="font-mono text-muted-foreground">{i + 1}.</span>
                    <span lang="en">{option}</span>
                  </Button>
                </li>
              ))}
            </ol>
            <p className="text-center text-xs text-muted-foreground max-md:hidden">
              {t.rich("choiceKeys", { k: kbd })}
            </p>
          </>
        )}

        {!answered && item.format === "find_fix" && segment === null && (
          <p className="text-center text-xs text-muted-foreground">{t.rich("findKeys", { k: kbd })}</p>
        )}

        {!answered && (item.format !== "choice4" && (item.format !== "find_fix" || segment !== null)) && (
          <form
            className="flex flex-col gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              if (item.format === "find_fix") submitFix();
              else if (text.trim()) submit({ text: text.trim() });
            }}
          >
            <label htmlFor={`answer-${item.id}`} className="text-[13px] text-muted-foreground">
              {t(`answerLabel.${item.format}`)}
            </label>
            {item.format === "cloze" || item.format === "find_fix" ? (
              <Input
                id={`answer-${item.id}`}
                lang="en"
                autoComplete="off"
                autoCapitalize="off"
                spellCheck={false}
                autoFocus
                value={text}
                maxLength={500}
                onChange={(e) => setText(e.target.value)}
              />
            ) : (
              <Textarea
                id={`answer-${item.id}`}
                lang="en"
                spellCheck={false}
                autoFocus
                value={text}
                maxLength={1000}
                onChange={(e) => setText(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                    e.preventDefault();
                    e.currentTarget.form?.requestSubmit();
                  }
                }}
              />
            )}
            <div className="flex items-center gap-2">
              <Button type="submit" disabled={busy || !text.trim()}>
                {busy ? t("grading") : t("submit")}
              </Button>
              {MODEL_GRADED.has(item.format) && <AiBadge feature="practice_grade" />}
              {item.format !== "find_fix" && (
                <span className="text-xs text-muted-foreground max-md:hidden">{t("enterHint")}</span>
              )}
            </div>
          </form>
        )}

        {error && <ErrorText>{error}</ErrorText>}

        {answered && reply && item.result && (
          <Verdict item={item} reply={replyText(item, reply)} />
        )}
        {answered && !item.result && (
          <p className="text-sm text-muted-foreground" data-testid="practice-reported">
            {t("reported")}
          </p>
        )}

        <div className="flex flex-wrap items-center justify-between gap-2">
          {item.status === "reported" ? (
            <span />
          ) : (
            <InlineConfirm
              question={t("reportConfirm")}
              confirmLabel={t("reportYes")}
              onConfirm={onReport}
            >
              {(ask) => (
                <Button variant="ghost" size="sm" disabled={busy} onClick={ask}>
                  <Flag />
                  {t("report")}
                </Button>
              )}
            </InlineConfirm>
          )}
          {answered && onNext && (
            <Button autoFocus onClick={onNext} data-testid="practice-next">
              {index + 1 < total ? t("next") : t("finish")}
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

function Question({
  item,
  segment,
  answered,
  onPick,
}: {
  item: Item;
  segment: number | null;
  answered: boolean;
  onPick: (i: number) => void;
}) {
  const t = useTranslations("practice.item");
  const c = item.content;
  // transform has no prompt of its own: its instruction says what to do.
  const prompt = item.format !== "transform" && (
    <p className="text-[13px] text-muted-foreground">{t(`prompt.${item.format}`)}</p>
  );
  const big = "text-xl leading-relaxed md:text-[22px]";
  switch (item.format) {
    case "choice4":
    case "cloze":
      return (
        <div className="flex flex-col gap-2">
          {prompt}
          <p className={big} lang="en" data-testid="practice-stem">
            <Stem text={c.stem ?? ""} blank={t("blank")} />
          </p>
          {c.hint && <p className="text-sm text-muted-foreground">{t("hint", { hint: c.hint })}</p>}
        </div>
      );
    case "find_fix":
      return (
        <div className="flex flex-col gap-2">
          {prompt}
          <p className={cn(big, "flex flex-wrap gap-y-1")} lang="en" data-testid="practice-segments">
            {(c.segments ?? []).map((piece, i) => (
              <button
                key={i}
                type="button"
                disabled={answered}
                aria-pressed={segment === i}
                aria-label={t("pickPiece", { n: i + 1, piece: piece.trim() })}
                onClick={() => onPick(i)}
                className={cn(
                  "rounded-md px-0.5 whitespace-pre underline decoration-dotted decoration-muted-foreground/60 underline-offset-[6px] outline-none hover:bg-accent focus-visible:outline-2 focus-visible:outline-ring disabled:no-underline disabled:hover:bg-transparent",
                  segment === i && "bg-accent text-accent-foreground decoration-solid",
                )}
              >
                {piece}
              </button>
            ))}
          </p>
        </div>
      );
    case "transform":
      return (
        <div className="flex flex-col gap-2">
          <p className="text-[13px] text-muted-foreground" lang="en">
            {c.instruction}
          </p>
          <p className={big} lang="en">
            {c.source}
          </p>
        </div>
      );
    case "translate":
      return (
        <div className="flex flex-col gap-2">
          {prompt}
          <p className={big}>{c.source}</p>
          {c.instruction && (
            <p className="text-sm text-muted-foreground" lang="en">
              {c.instruction}
            </p>
          )}
        </div>
      );
    case "rewrite_own":
      return (
        <div className="flex flex-col gap-2">
          {prompt}
          <blockquote className={cn(big, "border-l-2 pl-3")} lang="en">
            {c.original}
          </blockquote>
          {c.instruction && (
            <p className="text-sm text-muted-foreground" lang="en">
              {c.instruction}
            </p>
          )}
        </div>
      );
  }
}

function Verdict({ item, reply }: { item: Item; reply: string }) {
  const t = useTranslations("practice.item");
  const locale = useLocale();
  const result = item.result!;
  const key = keyText(item);
  const better = result.feedback.corrected;
  return (
    <div
      data-testid="practice-verdict"
      data-correct={result.correct}
      className={cn(
        "flex flex-col gap-2 rounded-lg border p-3.5 text-sm",
        result.correct
          ? "border-[color-mix(in_oklab,var(--success)_30%,transparent)] bg-[color-mix(in_oklab,var(--success)_8%,var(--card))]"
          : "border-[color-mix(in_oklab,var(--destructive)_30%,transparent)] bg-[color-mix(in_oklab,var(--destructive)_6%,var(--card))]",
      )}
    >
      <p className="flex items-center gap-1.5 font-semibold">
        {result.correct ? (
          <CircleCheck aria-hidden className="size-4 text-success" />
        ) : (
          <CircleX aria-hidden className="size-4 text-destructive" />
        )}
        {t(result.correct ? "right" : "wrong")}
      </p>
      <p>
        <span className="text-muted-foreground">{t("yours")}</span>{" "}
        <span lang="en" className={cn(!result.correct && "line-through decoration-destructive/70")}>
          {reply}
        </span>
      </p>
      {!result.correct && better && better !== reply && (
        <p>
          <span className="text-muted-foreground">{t("corrected")}</span>{" "}
          <span lang="en" className="font-[550] text-success">
            {better}
          </span>
        </p>
      )}
      {key && key !== reply && (
        <p>
          <span className="text-muted-foreground">{t("reference")}</span>{" "}
          <span lang="en" className="font-[550]">
            {key}
          </span>
        </p>
      )}
      <p className="whitespace-pre-line">{result.feedback.explanation}</p>
      {result.feedback.other_mistakes.length > 0 && (
        <div className="flex flex-col gap-1">
          <p className="text-xs font-semibold text-muted-foreground">{t("otherMistakes")}</p>
          <ul className="flex flex-col gap-1">
            {result.feedback.other_mistakes.map((m, i) => (
              <li key={i}>
                <span lang="en" className="text-muted-foreground line-through decoration-destructive/70">
                  {m.original}
                </span>
                {" → "}
                <span lang="en" className="font-[550] text-success">
                  {m.correction}
                </span>
                <span className="text-xs text-muted-foreground"> · {kcName(m.kc, locale)}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

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
