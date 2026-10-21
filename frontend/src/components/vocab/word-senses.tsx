"use client";

import { useTranslations } from "next-intl";

import { Tag } from "@/components/ui/tag";
import { markWord } from "@/lib/meanings";
import type { WordSense } from "@/lib/vocab";

/** Parts of speech as the Chinese senses above write them. */
const POS: Record<string, string> = {
  noun: "n.",
  "proper noun": "n.",
  verb: "v.",
  adjective: "adj.",
  adverb: "adv.",
  preposition: "prep.",
  pronoun: "pron.",
  conjunction: "conj.",
  determiner: "det.",
  interjection: "int.",
  phrase: "phr.",
  abbreviation: "abbr.",
  contraction: "contr.",
  prefix: "pref.",
  suffix: "suf.",
  number: "num.",
};

/**
 * English senses on the back of a flashcard (ADR 0062): part of speech, labels, the
 * definition and up to `examples` example sentences each, the word in bold.
 */
export function WordSenses({
  senses,
  forms,
  examples,
}: {
  senses: WordSense[];
  forms: string[];
  examples: number;
}) {
  const t = useTranslations("vocab.review.senses");
  const label = (name: string) => {
    const key = `labels.${name.replace(/[ .]/g, "_")}` as Parameters<typeof t>[0];
    return t.has(key) ? t(key) : name;
  };
  return (
    <ul className="flex flex-col gap-3" data-testid="review-senses">
      {senses.map((sense, i) => (
        <li key={i} className="flex flex-col gap-1">
          <p className="flex items-baseline gap-2 text-[15px] leading-relaxed">
            <span className="min-w-10 shrink-0 font-mono text-[13px] text-muted-foreground">
              {POS[sense.pos] ?? sense.pos}
            </span>
            <span className="min-w-0">
              {sense.labels.map((name) => (
                <Tag key={name} variant="outline" className="mr-1 align-[1px]">
                  {label(name)}
                </Tag>
              ))}
              <span lang="en">
                <Marked text={sense.gloss} forms={forms} />
              </span>
            </span>
          </p>
          {sense.examples.slice(0, examples).map((example) => (
            <p key={example} lang="en" className="pl-12 text-sm text-muted-foreground">
              <Marked text={example} forms={forms} />
            </p>
          ))}
        </li>
      ))}
    </ul>
  );
}

function Marked({ text, forms }: { text: string; forms: string[] }) {
  return markWord(text, forms).map((s, i) =>
    s.hit ? (
      <strong key={i} className="font-semibold text-foreground">
        {s.text}
      </strong>
    ) : (
      s.text
    ),
  );
}
