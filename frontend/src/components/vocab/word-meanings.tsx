"use client";

import { ChevronRight } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";

import { Tag } from "@/components/ui/tag";
import { type Sense, parseDefinition, parseTranslation } from "@/lib/meanings";
import { cn } from "@/lib/utils";
import type { Card } from "@/lib/vocab";

import { WordExamples } from "./word-examples";

/** English senses shown before "show all": the rest are mostly archaic or rare. */
const ENGLISH_FIRST = 3;

/**
 * The back of a flashcard (task 27.2–27.3): everyday Chinese senses by part of speech, then
 * example sentences (task 28.4); domain senses and the English definition folded under
 * "more", with the dictionary named.
 */
export function WordMeanings({ card }: { card: Card }) {
  const { word } = card;
  const t = useTranslations("vocab.review.meanings");
  const { main, domain } = parseTranslation(word.translation);
  const english = parseDefinition(word.definition);
  const [allEnglish, setAllEnglish] = useState(false);
  const shownEnglish = allEnglish ? english : english.slice(0, ENGLISH_FIRST);
  const more = [
    domain.length > 0 && t("domainCount", { count: domain.length }),
    english.length > 0 && t("english"),
  ].filter(Boolean);

  return (
    <div className="flex flex-col gap-4">
      <ul className="flex flex-col gap-2" data-testid="review-meanings">
        {main.map((sense, i) => (
          <SenseLine key={i} sense={sense} className="text-[17px] leading-[1.6]" />
        ))}
      </ul>
      <WordExamples wordId={word.id} sentences={card.sentences} forms={card.forms} />
      {more.length > 0 && (
        // Native <details>: closed by default, keyboard and screen-reader friendly for free.
        <details className="group border-t pt-3" data-testid="review-more">
          <summary className="flex cursor-pointer list-none items-center gap-1 text-[13px] text-muted-foreground select-none hover:text-foreground [&::-webkit-details-marker]:hidden">
            <ChevronRight aria-hidden className="size-4 transition-transform group-open:rotate-90" />
            {t("more")} · {more.join(" · ")}
          </summary>
          <div className="mt-3 flex flex-col gap-4 pl-5">
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
