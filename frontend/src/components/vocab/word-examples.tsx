"use client";

import { ExternalLink } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";

import { AiBadge } from "@/components/ai-badge";
import { ShadowingBadge, ShadowingButton } from "@/components/speech/shadowing-button";
import { ShadowingPanel } from "@/components/speech/shadowing-panel";
import { useDescribeError } from "@/components/settings/use-describe-error";
import { markWord } from "@/lib/meanings";
import { MAX_SHADOWING_CHARS, useShadowingMode } from "@/lib/shadowing";
import { cn } from "@/lib/utils";
import { type Example, type SourcedExample, fetchExamples } from "@/lib/vocab";
import { ErrorText } from "@/components/ui/error-text";
import { LingoCat } from "@/components/brand/lingo-cat";

/**
 * Example sentences on the back of a flashcard (task 28.4, ADR 0020): real ones from
 * Tatoeba, each linked to its page there; AI ones only when the learner asks, since each
 * uncached word is a model call, unless they were already written (ahead of time, task 44).
 */
export function WordExamples({
  wordId,
  sentences,
  forms,
  cached = [],
}: {
  wordId: number;
  sentences: SourcedExample[];
  forms: string[];
  /** AI sentences the queue already has for this word. */
  cached?: Example[];
}) {
  const t = useTranslations("vocab.review.examples");
  const describe = useDescribeError();
  const [ai, setAi] = useState<Example[] | null>(cached.length > 0 ? cached : null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // The example being shadowed, one at a time.
  const [shadowing, setShadowing] = useState<string | null>(null);
  const shadowable = useShadowingMode() !== null;
  const shadow = (en: string) =>
    shadowable && en.length <= MAX_SHADOWING_CHARS
      ? {
          open: shadowing === en,
          toggle: () => setShadowing(shadowing === en ? null : en),
          wordId,
        }
      : undefined;

  const load = async () => {
    setBusy(true);
    setError(null);
    try {
      setAi((await fetchExamples(wordId)).sentences);
    } catch (e) {
      setError(describe(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    // The rule beside the sentences marks them off from the meanings; a lone button needs none.
    <section
      className={cn("flex flex-col gap-2", (sentences.length > 0 || ai) && "border-l-2 pl-3")}
      data-testid="review-examples"
    >
      {sentences.length > 0 && (
        <ul className="flex flex-col gap-2.5">
          {sentences.map((s) => (
            <ExampleLine
              key={s.en}
              example={s}
              forms={forms}
              link={s.url}
              linkLabel={t("open")}
              shadowing={shadow(s.en)}
            />
          ))}
        </ul>
      )}
      {ai && (
        <ul className="flex flex-col gap-2.5" data-testid="review-ai-examples">
          {ai.map((s) => (
            <ExampleLine key={s.en} example={s} forms={forms} shadowing={shadow(s.en)} />
          ))}
        </ul>
      )}
      <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
        {sentences.length > 0 && <span>{t("source")}</span>}
        {shadowable && (sentences.length > 0 || ai) && (
          <span className="inline-flex items-center gap-1" data-testid="examples-shadowing-hint">
            {t("shadowing")}
            <ShadowingBadge />
          </span>
        )}
        {ai ? (
          <span>{t("aiSource")}</span>
        ) : (
          <span className="inline-flex items-center gap-1">
            {busy && <LingoCat mood="ai" size={16} label="" />}
            <button
              type="button"
              className="font-medium text-primary underline-offset-2 hover:underline disabled:opacity-60"
              disabled={busy}
              onClick={() => void load()}
            >
              {busy ? t("aiLoading") : t("ai")}
            </button>
            <AiBadge feature="word_examples" />
          </span>
        )}
      </p>
      {error && (
        <ErrorText size="xs">{error}</ErrorText>
      )}
    </section>
  );
}

function ExampleLine({
  example,
  forms,
  link,
  linkLabel,
  shadowing,
}: {
  example: Example;
  forms: string[];
  link?: string | null;
  linkLabel?: string;
  shadowing?: { open: boolean; toggle: () => void; wordId: number };
}) {
  const t = useTranslations("speech.shadowing");
  return (
    <li>
      <p lang="en" className="text-[15px] leading-relaxed">
        {markWord(example.en, forms).map((s, i) =>
          s.hit ? (
            <strong key={i} className="font-semibold">
              {s.text}
            </strong>
          ) : (
            s.text
          ),
        )}
        {shadowing && (
          <ShadowingButton
            compact
            open={shadowing.open}
            onToggle={shadowing.toggle}
            label={t("openSentence")}
            className="ml-1"
          />
        )}
      </p>
      <p className="text-sm text-muted-foreground">
        {example.zh}
        {link && (
          <a
            href={link}
            target="_blank"
            rel="noreferrer"
            aria-label={linkLabel}
            title={linkLabel}
            className="ml-1.5 inline-flex align-[-2px] text-muted-foreground/70 hover:text-foreground"
          >
            <ExternalLink aria-hidden className="size-3" />
          </a>
        )}
      </p>
      {shadowing?.open && (
        <ShadowingPanel
          sentences={[example.en]}
          source="vocab"
          sourceId={String(shadowing.wordId)}
          onClose={shadowing.toggle}
          className="mt-2"
        />
      )}
    </li>
  );
}
