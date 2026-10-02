"use client";

import { MessageCircle, RotateCcw, Trash2 } from "lucide-react";
import { useFormatter, useLocale, useTranslations } from "next-intl";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useId, useState } from "react";

import { CatLoading } from "@/components/brand/lingo-cat";
import { useDescribeError } from "@/components/settings/use-describe-error";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorText } from "@/components/ui/error-text";
import { Tag } from "@/components/ui/tag";
import { ApiError } from "@/lib/api";
import { kcName } from "@/lib/learner";
import type { KCName } from "@/lib/practice";
import { cn } from "@/lib/utils";
import {
  deleteSubmission,
  fetchSubmission,
  markMistakes,
  paragraphs,
  SCORE_NAMES,
  type SentenceCorrection,
  type Submission,
} from "@/lib/writing";

/** How often a review still running is polled. */
export const POLL_MS = 2000;

const FAILED_CODES = ["no_llm_configured", "review_failed", "interrupted"] as const;

/**
 * One piece of writing and its review (task 39.2): polled while the review runs; then
 * the sentences one by one with their mistakes marked (Q39b), the four scores, the
 * overall feedback and the words put on the word list. A failed review can be sent
 * again from the writing page (Q39e); deleting takes the mistakes out of the learner
 * model too (Q38e).
 */
export function WritingReview({ id }: { id: number }) {
  const t = useTranslations("writing.review");
  const tCat = useTranslations("cat");
  const describe = useDescribeError();
  const router = useRouter();
  const [submission, setSubmission] = useState<Submission | null>(null);
  const [missing, setMissing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    fetchSubmission(id).then(setSubmission, (e: unknown) => {
      if (e instanceof ApiError && e.status === 404) setMissing(true);
      else setError(describe(e));
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- once per id
  }, [id]);

  // Poll a review still running until it is done or failed.
  const pending = submission?.status === "pending";
  useEffect(() => {
    if (!pending) return;
    let live = true;
    const timer = setTimeout(() => {
      fetchSubmission(id).then(
        (s) => live && setSubmission(s),
        (e: unknown) => live && setError(describe(e)),
      );
    }, POLL_MS);
    return () => {
      live = false;
      clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- re-armed by each poll
  }, [pending, submission, id]);

  async function remove() {
    setBusy(true);
    setError(null);
    try {
      await deleteSubmission(id);
      router.push("/writing");
    } catch (e) {
      setError(describe(e));
      setBusy(false);
    }
  }

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="mx-auto flex max-w-2xl flex-col gap-3.5 p-4 md:gap-4 md:px-10 md:py-8">
        <Link href="/writing" className="text-sm text-muted-foreground hover:text-foreground">
          {t("back")}
        </Link>
        {missing && (
          <EmptyState
            tone="error"
            title={t("missing")}
            action={
              <Link href="/writing" className={buttonVariants({ size: "sm", variant: "outline" })}>
                {t("toWriting")}
              </Link>
            }
          />
        )}
        {!submission && !missing && !error && <CatLoading label={tCat("loader")} />}
        {error && <ErrorText>{error}</ErrorText>}
        {submission && (
          <>
            <Header submission={submission} />
            {submission.status === "pending" && (
              <Card data-testid="writing-pending">
                <CardContent>
                  <CatLoading mood="hop" size={72} label={t("pending")} />
                  <p className="text-center text-xs text-muted-foreground">{t("pendingNote")}</p>
                </CardContent>
              </Card>
            )}
            {submission.status === "failed" && <Failed submission={submission} />}
            {submission.status === "done" && <Review submission={submission} />}
            <div className="flex justify-end">
              <ConfirmDialog
                trigger={
                  <Button variant="ghost" size="sm" disabled={busy} data-testid="writing-delete">
                    <Trash2 />
                    {t("delete.button")}
                  </Button>
                }
                title={t("delete.title")}
                description={t("delete.description")}
                onConfirm={() => void remove()}
              />
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function Header({ submission: s }: { submission: Submission }) {
  const t = useTranslations("writing.review");
  const format = useFormatter();
  return (
    <Card>
      <CardHeader>
        <CardTitle>
          <h1 lang={s.prompt ? "en" : undefined}>{s.prompt || t("untitled")}</h1>
        </CardTitle>
        <CardDescription>
          {format.dateTime(new Date(s.created_at), { dateStyle: "medium", timeStyle: "short" })}
          {" · "}
          {t("wordCount", { n: s.word_count })}
        </CardDescription>
      </CardHeader>
      {s.from_conversation && (
        <CardContent className="text-sm">
          <p className="flex items-center gap-1.5 text-muted-foreground">
            <MessageCircle aria-hidden className="size-4" />
            {s.conversation_id ? (
              <Link href={`/chat?c=${s.conversation_id}`} className="text-primary hover:underline">
                {t("fromChat")}
              </Link>
            ) : (
              t("fromDeletedChat")
            )}
          </p>
        </CardContent>
      )}
    </Card>
  );
}

function Failed({ submission: s }: { submission: Submission }) {
  const t = useTranslations("writing.review");
  const known = FAILED_CODES.find((c) => c === s.error_code);
  return (
    <EmptyState
      tone="error"
      data-testid="writing-failed"
      title={t("failed.title")}
      description={known ? t(`failed.${known}`) : t("failed.other")}
      action={
        <Link
          href={`/writing?again=${s.id}`}
          className={buttonVariants({ size: "sm", variant: "outline" })}
        >
          <RotateCcw />
          {t("failed.again")}
        </Link>
      }
    />
  );
}

function Review({ submission: s }: { submission: Submission }) {
  const t = useTranslations("writing.review");
  const kcs = new Map(s.kcs.map((kc) => [kc.id, kc]));
  const mistakes = (s.corrections ?? []).reduce((n, c) => n + c.mistakes.length, 0);
  const added = (s.words ?? []).filter((w) => w.added);
  const known = (s.words ?? []).filter((w) => !w.added);
  return (
    <>
      <Card data-testid="writing-summary">
        <CardHeader>
          <CardTitle>
            <h2>{t("summary")}</h2>
          </CardTitle>
          <CardDescription>
            {mistakes === 0 ? t("noMistakes") : t("mistakes", { n: mistakes })}
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4 text-sm">
          {s.summary && <p>{s.summary}</p>}
          {s.scores && (
            <section aria-labelledby="writing-scores">
              <h3 id="writing-scores" className="mb-1.5 font-semibold">
                {t("scores.heading")}
              </h3>
              <dl className="grid gap-2 sm:grid-cols-2">
                {SCORE_NAMES.map((name) => {
                  const score = s.scores?.[name];
                  if (!score) return null;
                  return (
                    <div key={name} className="rounded-lg bg-muted/60 px-3 py-2" data-testid="writing-score">
                      <dt className="flex items-center justify-between text-xs font-semibold">
                        {t(`scores.${name}`)}
                        <span className="tabular-nums">{t("scores.value", { n: score.score })}</span>
                      </dt>
                      <dd className="text-xs text-muted-foreground">{score.reason}</dd>
                    </div>
                  );
                })}
              </dl>
              <p className="mt-1.5 text-xs text-muted-foreground">{t("scores.note")}</p>
            </section>
          )}
          {(added.length > 0 || known.length > 0) && (
            <section aria-labelledby="writing-words" className="flex flex-col gap-1">
              <h3 id="writing-words" className="font-semibold">
                {t("words.heading")}
              </h3>
              {added.length > 0 && (
                <p>
                  {t("words.added")}{" "}
                  <span lang="en">{added.map((w) => w.word).join(", ")}</span>
                  {" · "}
                  <Link href="/vocab/mine" className="text-primary hover:underline">
                    {t("words.manage")}
                  </Link>
                </p>
              )}
              {known.length > 0 && (
                <p className="text-muted-foreground">
                  {t("words.existing")} <span lang="en">{known.map((w) => w.word).join(", ")}</span>
                </p>
              )}
            </section>
          )}
          {s.model && <p className="text-xs text-muted-foreground">{t("model", { model: s.model })}</p>}
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>
            <h2>{t("sentences")}</h2>
          </CardTitle>
          <CardDescription>{t("sentencesHint")}</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          {paragraphs(s.corrections ?? []).map((sentences, i) => (
            <div key={i} className="flex flex-col gap-2" lang="en">
              {sentences.map((sentence) => (
                <Sentence key={sentence.index} sentence={sentence} kcs={kcs} />
              ))}
            </div>
          ))}
        </CardContent>
      </Card>
    </>
  );
}

function Sentence({ sentence, kcs }: { sentence: SentenceCorrection; kcs: Map<string, KCName> }) {
  const t = useTranslations("writing.review");
  const locale = useLocale();
  const [open, setOpen] = useState<number | null>(null);
  const detailsId = useId();
  if (!sentence.corrected && sentence.mistakes.length === 0) {
    return (
      <p className="text-sm leading-relaxed" data-testid="writing-sentence">
        {sentence.original}
      </p>
    );
  }
  const shown = open === null ? null : sentence.mistakes[open];
  const pieces = markMistakes(sentence.original, sentence.mistakes);
  // Parts that overlap an earlier one can't be marked in the sentence: listed after it.
  const marked = new Set(pieces.map((p) => p.mistake));
  const unmarked = sentence.mistakes.flatMap((m, i) => (marked.has(i) ? [] : [i]));
  const mark = (index: number, text: string, key: number | string) => (
    <button
      key={key}
      type="button"
      aria-expanded={open === index}
      aria-controls={detailsId}
      aria-label={t("mistakeLabel", { text })}
      onClick={() => setOpen(open === index ? null : index)}
      className={cn(
        "rounded-[3px] bg-[color-mix(in_oklab,var(--warning)_18%,transparent)] px-0.5 underline decoration-warning decoration-wavy underline-offset-4 outline-none hover:bg-[color-mix(in_oklab,var(--warning)_30%,transparent)] focus-visible:outline-2 focus-visible:outline-ring",
        open === index && "bg-[color-mix(in_oklab,var(--warning)_30%,transparent)]",
      )}
    >
      {text}
    </button>
  );
  return (
    <div
      className="flex flex-col gap-1.5 rounded-lg border-l-2 border-warning bg-muted/40 px-3 py-2 text-sm leading-relaxed"
      data-testid="writing-sentence"
    >
      <p>
        {pieces.map((piece, i) =>
          piece.mistake === null ? <span key={i}>{piece.text}</span> : mark(piece.mistake, piece.text, i),
        )}
        {unmarked.map((index) => (
          <span key={`u${index}`} className="ml-1.5">
            {mark(index, sentence.mistakes[index].original, index)}
          </span>
        ))}
      </p>
      {sentence.corrected && (
        <p className="text-success" data-testid="writing-corrected">
          <span className="sr-only">{t("corrected")} </span>
          <span aria-hidden className="mr-1">
            →
          </span>
          {sentence.corrected}
        </p>
      )}
      <div id={detailsId} lang={locale}>
        {shown && (
          <p className="rounded-md bg-card px-2.5 py-1.5 text-xs" data-testid="writing-explanation">
            <span lang="en" className="font-semibold">
              {shown.original} → {shown.correction}
            </span>
            {kcs.get(shown.kc_id) && (
              <Tag variant="outline" className="ml-1.5">
                {kcName(kcs.get(shown.kc_id)!, locale)}
              </Tag>
            )}
            <span className="mt-0.5 block text-muted-foreground">{shown.explanation}</span>
          </p>
        )}
      </div>
    </div>
  );
}
