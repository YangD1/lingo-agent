"use client";

import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useFormatter, useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import { useDescribeError } from "@/components/settings/use-describe-error";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorText } from "@/components/ui/error-text";
import { Input } from "@/components/ui/input";
import { type Card as VocabCard, fetchKnown, unmarkKnown } from "@/lib/vocab";

const PAGE = 50;
const SEARCH_DELAY_MS = 250;

/**
 * Known words (task 120): every word not reviewed because it is known, whether marked on a
 * card, in screening or from the placement test. Adding one back puts it into review again,
 * from where it left off.
 */
export function KnownApp() {
  const t = useTranslations("vocab.known");
  const describe = useDescribeError();
  const [text, setText] = useState("");
  const [q, setQ] = useState("");
  // The search the list below is for, so typing doesn't show another search's words.
  const [page, setPage] = useState<{ q: string; words: VocabCard[]; total: number } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState<number | null>(null);

  useEffect(() => {
    const timer = setTimeout(() => setQ(text.trim()), SEARCH_DELAY_MS);
    return () => clearTimeout(timer);
  }, [text]);

  useEffect(() => {
    let live = true;
    fetchKnown(q, PAGE, 0).then(
      (found) => live && setPage({ q, ...found }),
      (e: unknown) => live && setError(describe(e)),
    );
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- describe is stable enough
  }, [q]);

  async function addBack(card: VocabCard) {
    setBusy(card.word.id);
    setError(null);
    setNotice(null);
    try {
      await unmarkKnown(card.word.id);
      const word = card.word.word;
      setNotice(card.last_review ? t("addedBackReview", { word }) : t("addedBackNew", { word }));
      setPage((p) =>
        p && { ...p, words: p.words.filter((c) => c.word.id !== card.word.id), total: p.total - 1 },
      );
    } catch (e) {
      setError(describe(e));
    } finally {
      setBusy(null);
    }
  }

  async function more() {
    if (!page) return;
    try {
      const next = await fetchKnown(page.q, PAGE, page.words.length);
      setPage({ q: page.q, words: [...page.words, ...next.words], total: next.total });
    } catch (e) {
      setError(describe(e));
    }
  }

  return (
    <div className="pet-safe flex-1 overflow-y-auto">
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
            <Input
              type="search"
              aria-label={t("searchLabel")}
              placeholder={t("searchPlaceholder")}
              autoComplete="off"
              maxLength={100}
              value={text}
              onChange={(e) => setText(e.target.value)}
            />
            {error && <ErrorText>{error}</ErrorText>}
            {notice && (
              <p role="status" className="text-sm text-muted-foreground">
                {notice}
              </p>
            )}

            {page?.total === 0 &&
              (page.q ? (
                <p className="py-6 text-center text-sm text-muted-foreground">
                  {t("noMatch", { q: page.q })}
                </p>
              ) : (
                <EmptyState title={t("empty")} description={t("emptyHint")} />
              ))}
            {page && page.words.length > 0 && (
              <ul className="flex flex-col divide-y" aria-label={t("title")}>
                {page.words.map((card) => (
                  <KnownRow
                    key={card.word.id}
                    card={card}
                    busy={busy === card.word.id}
                    onAddBack={() => void addBack(card)}
                  />
                ))}
              </ul>
            )}
            {page && page.words.length < page.total && (
              <Button variant="ghost" className="self-center" onClick={() => void more()}>
                {t("more", { left: page.total - page.words.length })}
              </Button>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function KnownRow({
  card,
  busy,
  onAddBack,
}: {
  card: VocabCard;
  busy: boolean;
  onAddBack: () => void;
}) {
  const t = useTranslations("vocab.known");
  const format = useFormatter();
  const source = card.source === "auto" ? "manual" : (card.source ?? "book");
  return (
    <li className="flex items-center gap-3 py-3" data-testid={`known-${card.word.word}`}>
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <div className="flex flex-wrap items-baseline gap-2">
          <span className="font-semibold" lang="en">
            {card.word.word}
          </span>
          {card.word.phonetic && (
            <span className="font-mono text-xs text-muted-foreground">/{card.word.phonetic}/</span>
          )}
        </div>
        <p className="truncate text-[13px]">{card.word.translation.split("\n")[0]}</p>
        <p className="text-xs text-muted-foreground">
          {t(`sources.${source}`)}
          {card.last_review &&
            ` · ${t("lastReview", { when: format.relativeTime(new Date(card.last_review)) })}`}
        </p>
      </div>
      <Button variant="outline" size="sm" disabled={busy} onClick={onAddBack}>
        {t("addBack")}
      </Button>
    </li>
  );
}
