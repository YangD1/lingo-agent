"use client";

import { Volume2 } from "lucide-react";
import { useTranslations } from "next-intl";

import { ReadAloudBadge } from "@/components/speech/read-aloud-badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Tag } from "@/components/ui/tag";
import { speakWord } from "@/lib/speech";
import { cn } from "@/lib/utils";
import { type SpellResult, spellingMarks } from "@/lib/vocab";

/** How a listening or spelling card was answered; null `picked` / `typed`: gave up. */
export type Answer =
  | { format: "listen"; picked: string | null; right: boolean }
  | { format: "spell"; typed: string | null; result: SpellResult };

export const SPELL_FORM = "review-spell";

function PlayButton({ word }: { word: string }) {
  const t = useTranslations("vocab.review");
  return (
    <div className="flex items-center gap-2">
      {/* Read when the card shows; this is for again, and for when the browser blocked that. */}
      <Button
        variant="outline"
        size="icon-lg"
        className="size-16 rounded-full [&_svg]:size-7"
        aria-label={t("play")}
        title={t("play")}
        onClick={() => speakWord(word)}
        data-testid="review-play"
      >
        <Volume2 />
      </Button>
      <ReadAloudBadge />
    </div>
  );
}

/** Listening card (task 63): hear the word, pick its meaning of four (keys 1–4). */
export function ListenFront({
  word,
  options,
  onPick,
}: {
  word: string;
  options: string[];
  onPick: (option: string) => void;
}) {
  const t = useTranslations("vocab.review");
  return (
    <div className="flex flex-col items-center gap-5 pt-4 text-center" data-testid="review-listen">
      <PlayButton word={word} />
      <p className="text-sm text-muted-foreground">{t("listen.prompt")}</p>
      <div className="grid w-full gap-2" role="group" aria-label={t("listen.options")}>
        {options.map((option, i) => (
          <Button
            key={option}
            variant="outline"
            className="h-auto min-h-11 justify-start gap-3 py-2 text-left whitespace-normal"
            onClick={() => onPick(option)}
          >
            <span
              aria-hidden
              className="font-mono text-xs text-muted-foreground max-md:hidden"
            >
              {i + 1}
            </span>
            {option}
          </Button>
        ))}
      </div>
    </div>
  );
}

/** Spelling card (task 63): hear the word and see its meaning, type it (Q63h). */
export function SpellFront({
  word,
  gloss,
  typed,
  onType,
  onSubmit,
}: {
  word: string;
  gloss: string;
  typed: string;
  onType: (typed: string) => void;
  onSubmit: () => void;
}) {
  const t = useTranslations("vocab.review");
  return (
    <div className="flex flex-col items-center gap-5 pt-4 text-center" data-testid="review-spell">
      <PlayButton word={word} />
      <p className="text-sm text-muted-foreground">{t("spell.prompt")}</p>
      <p className="text-lg font-medium">{gloss}</p>
      <form
        id={SPELL_FORM}
        className="w-full"
        onSubmit={(event) => {
          event.preventDefault();
          onSubmit();
        }}
      >
        <Input
          autoFocus
          value={typed}
          onChange={(event) => onType(event.target.value)}
          aria-label={t("spell.input")}
          lang="en"
          autoComplete="off"
          autoCapitalize="off"
          autoCorrect="off"
          spellCheck={false}
          className="h-12 text-center text-xl"
        />
      </form>
    </div>
  );
}

/** What the answer was, on the back of a listening or spelling card. */
export function AnswerResult({ answer, word }: { answer: Answer; word: string }) {
  const t = useTranslations("vocab.review");
  if (answer.format === "listen") {
    return (
      <p className="flex flex-wrap items-center gap-2" data-testid="review-result">
        {answer.picked === null ? (
          <Tag variant="warning">{t("listen.skipped")}</Tag>
        ) : answer.right ? (
          <Tag variant="success">{t("listen.right")}</Tag>
        ) : (
          <>
            <Tag variant="destructive">{t("listen.wrong")}</Tag>
            <span className="text-sm text-muted-foreground">
              {t("listen.picked", { picked: answer.picked })}
            </span>
          </>
        )}
      </p>
    );
  }
  const variant = { right: "success", close: "warning", wrong: "destructive" } as const;
  return (
    <div className="flex flex-col gap-1.5" data-testid="review-result">
      <p className="flex flex-wrap items-center gap-2">
        <Tag variant={answer.typed === null ? "warning" : variant[answer.result]}>
          {answer.typed === null ? t("spell.skipped") : t(`spell.${answer.result}`)}
        </Tag>
        {answer.typed !== null && answer.result !== "right" && (
          <span className="text-sm text-muted-foreground" lang="en">
            {t("spell.typed", { typed: answer.typed.trim() })}
          </span>
        )}
      </p>
      {answer.typed !== null && answer.result !== "right" && (
        <p className="font-mono text-lg tracking-wide" lang="en" aria-label={t("spell.answer")}>
          {spellingMarks(answer.typed, word).map((mark, i) => (
            <span
              key={i}
              className={cn(!mark.ok && "text-destructive underline decoration-2 underline-offset-4")}
            >
              {mark.char}
            </span>
          ))}
        </p>
      )}
    </div>
  );
}
