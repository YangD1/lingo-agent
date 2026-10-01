"use client";

import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useFormatter, useTranslations } from "next-intl";
import { type FormEvent, useCallback, useEffect, useState } from "react";

import { useDescribeError } from "@/components/settings/use-describe-error";
import { AutocompleteInput } from "@/components/ui/autocomplete";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { InlineConfirm } from "@/components/ui/inline-confirm";
import { ErrorText } from "@/components/ui/error-text";
import { addMine, type Card as VocabCard, fetchMine, removeMine, suggestWords } from "@/lib/vocab";

const PAGE = 50;
// The server's largest page, for reloading everything shown so far.
const MAX_PAGE = 200;
const SUGGEST_DELAY_MS = 200;

/**
 * The learner's own word list (生词本): words they added here, or the tutor picked up in
 * conversation. They are learned before book words. Removing one deletes it for good,
 * with its review history.
 */
export function MineApp() {
  const t = useTranslations("vocab.mine");
  const describe = useDescribeError();
  const [words, setWords] = useState<VocabCard[]>([]);
  const [total, setTotal] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [text, setText] = useState("");
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);

  const reload = useCallback(
    (count: number = PAGE) =>
      fetchMine(Math.min(Math.max(count, PAGE), MAX_PAGE), 0).then(
        (page) => {
          setWords(page.words);
          setTotal(page.total);
        },
        (e: unknown) => setError(describe(e)),
      ),
    // eslint-disable-next-line react-hooks/exhaustive-deps -- describe is stable enough
    [],
  );

  useEffect(() => {
    void reload();
  }, [reload]);

  useEffect(() => {
    const prefix = text.trim();
    if (!prefix) return;
    let live = true;
    const timer = setTimeout(() => {
      suggestWords(prefix).then(
        (found) => live && setSuggestions(found.map((w) => w.word)),
        () => {}, // suggestions are a convenience
      );
    }, SUGGEST_DELAY_MS);
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [text]);

  async function add(event: FormEvent) {
    event.preventDefault();
    const typed = text.trim();
    if (!typed) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const result = await addMine(typed);
      const word = result.card.word.word;
      setNotice(
        !result.added
          ? t("already", { word })
          : result.matched === "lemma"
            ? t("addedLemma", { word, typed })
            : t("added", { word }),
      );
      setText("");
      setSuggestions([]);
      await reload(words.length + 1);
    } catch (e) {
      setError(describe(e));
    } finally {
      setBusy(false);
    }
  }

  async function remove(card: VocabCard) {
    setError(null);
    setNotice(null);
    try {
      await removeMine(card.word.id);
      await reload(words.length);
    } catch (e) {
      setError(describe(e));
    }
  }

  async function more() {
    try {
      const page = await fetchMine(PAGE, words.length);
      setWords([...words, ...page.words]);
      setTotal(page.total);
    } catch (e) {
      setError(describe(e));
    }
  }

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="mx-auto flex max-w-3xl flex-col gap-3.5 p-4 md:gap-4 md:px-10 md:py-8">
        <div className="flex items-center gap-2">
          <Link
            href="/vocab"
            aria-label={t("back")}
            title={t("back")}
            className={buttonVariants({ size: "icon-sm", variant: "ghost" })}
          >
            <ArrowLeft />
          </Link>
          <h1 className="text-[26px] font-bold tracking-tight">{t("title")}</h1>
        </div>
        <Card>
          <CardHeader>
            <CardTitle>{t("title")}</CardTitle>
            <CardDescription>{t("description")}</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            <form className="flex gap-2" onSubmit={(e) => void add(e)}>
              <AutocompleteInput
                aria-label={t("addLabel")}
                placeholder={t("addPlaceholder")}
                autoComplete="off"
                maxLength={100}
                value={text}
                onValueChange={setText}
                items={text.trim() ? suggestions : []}
              />
              <Button type="submit" disabled={busy || !text.trim()} className="shrink-0">
                {t("add")}
              </Button>
            </form>
            {error && (
              <ErrorText>{error}</ErrorText>
            )}
            {notice && (
              <p role="status" className="text-sm text-muted-foreground">
                {notice}
              </p>
            )}

            {total === 0 && (
              <EmptyState title={t("empty")} description={t("emptyHint")} />
            )}
            {words.length > 0 && (
              <ul className="flex flex-col divide-y" aria-label={t("title")}>
                {words.map((card) => (
                  <MineRow key={card.word.id} card={card} onRemove={() => void remove(card)} />
                ))}
              </ul>
            )}
            {total !== null && words.length < total && (
              <Button variant="ghost" className="self-center" onClick={() => void more()}>
                {t("more", { left: total - words.length })}
              </Button>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function MineRow({ card, onRemove }: { card: VocabCard; onRemove: () => void }) {
  const t = useTranslations("vocab.mine");
  const format = useFormatter();
  const status = card.status ?? "new";
  return (
    <li className="flex items-center gap-3 py-3" data-testid={`mine-${card.word.word}`}>
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <div className="flex flex-wrap items-baseline gap-2">
          <span className="font-semibold" lang="en">
            {card.word.word}
          </span>
          {card.word.phonetic && (
            <span className="font-mono text-xs text-muted-foreground">/{card.word.phonetic}/</span>
          )}
        </div>
        <p className="truncate text-[13px]">
          {card.word.translation.split("\n")[0]}
        </p>
        <p className="text-xs text-muted-foreground">
          {t(`sources.${card.source === "auto" ? "auto" : "manual"}`)} ·{" "}
          {t(`statuses.${status}`)}
          {status === "learning" &&
            card.due &&
            ` · ${t("due", { when: format.relativeTime(new Date(card.due)) })}`}
        </p>
      </div>
      <InlineConfirm question={t("confirmRemove", { word: card.word.word })} onConfirm={onRemove}>
        {(ask) => (
          <Button
            variant="ghost"
            size="sm"
            className="text-muted-foreground hover:text-foreground"
            onClick={ask}
          >
            {t("remove")}
          </Button>
        )}
      </InlineConfirm>
    </li>
  );
}
