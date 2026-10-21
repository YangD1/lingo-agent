"use client";

import { ChevronRight } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";

import { Tag } from "@/components/ui/tag";
import { type Sense, parseDefinition, parseTranslation } from "@/lib/meanings";
import { cn } from "@/lib/utils";
import type { Card } from "@/lib/vocab";

import { WordExamples } from "./word-examples";
import { WordSenses } from "./word-senses";

/** English senses shown before "show all": the rest are mostly archaic or rare. */
const ENGLISH_FIRST = 3;
/** Dictionary senses shown open (Q121a), one example each; the rest wait under "more". */
const SENSES_FIRST = 2;

/**
 * The back of a flashcard (task 27.2–27.3): everyday Chinese senses by part of speech,
 * the first English senses with an example each (ADR 0062), then example sentences (task
 * 28.4); domain senses and the other English senses folded under "more", with the
 * dictionaries named. Without dictionary senses, ECDICT's English definition stands in.
 */
export function WordMeanings({ card }: { card: Card }) {
  const { word } = card;
  const t = useTranslations("vocab.review.meanings");
  const ts = useTranslations("vocab.review.senses");
  const { main, domain } = parseTranslation(word.translation);
  const senses = card.senses ?? [];
  const restSenses = senses.slice(SENSES_FIRST);
  // Dictionary senses replace ECDICT's definition (Q121d).
  const english = senses.length > 0 ? [] : parseDefinition(word.definition);
  const [allEnglish, setAllEnglish] = useState(false);
  const shownEnglish = allEnglish ? english : english.slice(0, ENGLISH_FIRST);
  const more = [
    restSenses.length > 0 && ts("more", { count: restSenses.length }),
    domain.length > 0 && t("domainCount", { count: domain.length }),
    english.length > 0 && t("english"),
  ].filter(Boolean);
  const source = senses[0]?.url ? (
    <a
      href={senses[0].url}
      target="_blank"
      rel="noreferrer"
      className="underline-offset-2 hover:text-foreground hover:underline"
    >
      {ts("source")}
    </a>
  ) : (
    <span>{ts("source")}</span>
  );

  return (
    <div className="flex flex-col gap-4">
      <ul className="flex flex-col gap-2" data-testid="review-meanings">
        {main.map((sense, i) => (
          <SenseLine key={i} sense={sense} className="text-[17px] leading-[1.6]" />
        ))}
      </ul>
      {senses.length > 0 && (
        <section className="flex flex-col gap-1.5">
          <WordSenses senses={senses.slice(0, SENSES_FIRST)} forms={card.forms} examples={1} />
          {restSenses.length === 0 && <p className="text-xs text-muted-foreground">{source}</p>}
        </section>
      )}
      <WordExamples
        key={word.id}
        wordId={word.id}
        sentences={card.sentences}
        forms={card.forms}
        cached={card.ai_examples}
      />
      {more.length > 0 && (
        // Native <details>: closed by default, keyboard and screen-reader friendly for free.
        <details className="group border-t pt-3" data-testid="review-more">
          <summary className="flex cursor-pointer list-none items-center gap-1 text-[13px] text-muted-foreground select-none hover:text-foreground [&::-webkit-details-marker]:hidden">
            <ChevronRight aria-hidden className="size-4 transition-transform group-open:rotate-90" />
            {t("more")} · {more.join(" · ")}
          </summary>
          <div className="mt-3 flex flex-col gap-4 pl-5">
            {restSenses.length > 0 && (
              <section className="flex flex-col gap-1.5">
                <WordSenses senses={restSenses} forms={card.forms} examples={3} />
                <p className="text-xs text-muted-foreground">{source}</p>
              </section>
            )}
            {domain.length > 0 && (
              <ul className="flex flex-col gap-1.5">
                {domain.map((sense, i) => (
                  <SenseLine key={i} sense={sense} className="text-sm" />
                ))}
              </ul>
            )}
            {english.length > 0 && (
              <section className="flex flex-col gap-1.5">
                <ul className="flex flex-col gap-1.5" lang="en">
                  {shownEnglish.map((sense, i) => (
                    <SenseLine key={i} sense={sense} className="text-sm text-muted-foreground" />
                  ))}
                </ul>
                <p className="flex items-center gap-3 text-xs text-muted-foreground">
                  {english.length > ENGLISH_FIRST && !allEnglish && (
                    <button
                      type="button"
                      className="font-medium text-primary underline-offset-2 hover:underline"
                      onClick={() => setAllEnglish(true)}
                    >
                      {t("showAll", { count: english.length })}
                    </button>
                  )}
                  <span>{t("source")}</span>
                </p>
              </section>
            )}
          </div>
        </details>
      )}
    </div>
  );
}

function SenseLine({ sense, className }: { sense: Sense; className: string }) {
  return (
    <li className={cn("flex items-baseline gap-2", className)}>
      {(sense.pos || sense.domain) && (
        <span className="flex shrink-0 gap-1">
          {sense.pos && (
            <span className="min-w-10 font-mono text-[13px] text-muted-foreground">{sense.pos}</span>
          )}
          {sense.domain && <Tag variant="outline">{sense.domain}</Tag>}
        </span>
      )}
      <span className="min-w-0">{sense.text}</span>
    </li>
  );
}
