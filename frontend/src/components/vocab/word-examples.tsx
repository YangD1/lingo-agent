"use client";

import { ExternalLink } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";

import { AiBadge } from "@/components/ai-badge";
import { useDescribeError } from "@/components/settings/use-describe-error";
import { markWord } from "@/lib/meanings";
import { cn } from "@/lib/utils";
import { type Example, type SourcedExample, fetchExamples } from "@/lib/vocab";
import { ErrorText } from "@/components/ui/error-text";
import { LingoCat } from "@/components/brand/lingo-cat";

/**
 * Example sentences on the back of a flashcard (task 28.4, ADR 0020): real ones from
 * Tatoeba, each linked to its page there; AI ones only when the learner asks, since each
 * uncached word is a model call.
 */
export function WordExamples({
  wordId,
  sentences,
  forms,
}: {
  wordId: number;
  sentences: SourcedExample[];
  forms: string[];
}) {
  const t = useTranslations("vocab.review.examples");
  const describe = useDescribeError();
  const [ai, setAi] = useState<Example[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

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
            <ExampleLine key={s.en} example={s} forms={forms} link={s.url} linkLabel={t("open")} />
          ))}
        </ul>
      )}
      {ai && (
        <ul className="flex flex-col gap-2.5" data-testid="review-ai-examples">
          {ai.map((s) => (
            <ExampleLine key={s.en} example={s} forms={forms} />
          ))}
        </ul>
      )}
      <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
        {sentences.length > 0 && <span>{t("source")}</span>}
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
}: {
  example: Example;
  forms: string[];
  link?: string | null;
  linkLabel?: string;
}) {
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
    </li>
  );
}
