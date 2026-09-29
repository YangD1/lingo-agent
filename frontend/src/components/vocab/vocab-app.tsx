"use client";

import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { useCallback, useEffect, useState } from "react";

import { useDescribeError } from "@/components/settings/use-describe-error";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  type BookProgress,
  bookName,
  bookPercent,
  chooseBook,
  DAILY_NEW_MAX,
  fetchVocab,
  type VocabOverview,
} from "@/lib/vocab";

/**
 * Vocabulary home (P1 plan §6): today's reviews and new words, the word books with
 * progress in each, and how many new words a day.
 */
export function VocabApp() {
  const t = useTranslations("vocab");
  const locale = useLocale();
  const describe = useDescribeError();
  const [overview, setOverview] = useState<VocabOverview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(
    () => fetchVocab().then(setOverview, (e: unknown) => setError(describe(e))),
    // eslint-disable-next-line react-hooks/exhaustive-deps -- describe is stable enough
    [],
  );

  useEffect(() => {
    void load();
  }, [load]);

  async function save(bookId: string, dailyNew: number | null) {
    setBusy(true);
    setError(null);
    try {
      await chooseBook(bookId, dailyNew);
      await load();
    } catch (e) {
      setError(describe(e));
    } finally {
      setBusy(false);
    }
  }

  const current = overview?.books.find((b) => b.id === overview.book_id) ?? null;
  const today = overview?.today;
  const work = today ? today.reviews_due + today.new_left : 0;

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="mx-auto flex max-w-3xl flex-col gap-6 p-4 md:p-8">
        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}
        {overview && today && (
          <Card data-testid="vocab-today">
            <CardHeader>
              <CardTitle>{t("today.title")}</CardTitle>
              <CardDescription>
                {current
                  ? t("today.book", { book: bookName(current, locale) })
                  : t("today.noBook")}
              </CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-3">
              <p className="text-sm" data-testid="today-counts">
                {t("today.counts", {
                  reviews: today.reviews_due,
                  left: today.new_left,
                  started: today.new_started,
                  limit: today.new_limit,
                })}
              </p>
              {work === 0 && <p className="text-sm text-muted-foreground">{t("today.done")}</p>}
              {current && !overview.screened && (
                <p className="text-sm text-muted-foreground">{t("today.screenHint")}</p>
              )}
              <div className="flex flex-wrap gap-2">
                {work > 0 && (
                  <Link href="/vocab/review" className={buttonVariants({ size: "sm" })}>
                    {t("today.start")}
                  </Link>
                )}
                {today.new_left > 0 && today.reviews_due > 0 && (
                  <Link
                    href="/vocab/review?mode=new"
                    className={buttonVariants({ size: "sm", variant: "outline" })}
                  >
                    {t("today.newOnly")}
                  </Link>
                )}
                {current && (
                  <Link
                    href="/vocab/screen"
                    className={buttonVariants({ size: "sm", variant: "outline" })}
                  >
                    {t("today.screen")}
                  </Link>
                )}
                <Link
                  href="/vocab/mine"
                  className={buttonVariants({ size: "sm", variant: "outline" })}
                >
                  {t("today.mine")}
                </Link>
              </div>
            </CardContent>
          </Card>
        )}

        {overview && (
          <Card data-testid="vocab-books">
            <CardHeader>
              <CardTitle>{t("books.title")}</CardTitle>
              <CardDescription>{t("books.description")}</CardDescription>
            </CardHeader>
            <CardContent>
              <ul className="flex flex-col divide-y" aria-label={t("books.title")}>
                {overview.books.map((book) => (
                  <BookRow
                    key={book.id}
                    book={book}
                    current={book.id === overview.book_id}
                    disabled={busy}
                    onChoose={() => void save(book.id, overview.daily_new)}
                  />
                ))}
              </ul>
            </CardContent>
          </Card>
        )}

        {overview && overview.book_id && (
          <DailyNewCard
            key={`${overview.book_id}:${overview.daily_new}`}
            overview={overview}
            disabled={busy}
            onSave={(n) => void save(overview.book_id!, n)}
          />
        )}
      </div>
    </div>
  );
}

function BookRow({
  book,
  current,
  disabled,
  onChoose,
}: {
  book: BookProgress;
  current: boolean;
  disabled: boolean;
  onChoose: () => void;
}) {
  const t = useTranslations("vocab.books");
  const locale = useLocale();
  const percent = bookPercent(book);
  return (
    <li className="flex flex-col gap-2 py-3" data-testid={`book-${book.id}`}>
      <div className="flex items-center gap-2">
        <span className="font-medium">{bookName(book, locale)}</span>
        <span className="text-xs text-muted-foreground">{t("size", { total: book.total })}</span>
        <div className="ml-auto">
          {current ? (
            <span className="rounded-md bg-primary/10 px-2 py-0.5 text-xs text-primary">
              {t("current")}
            </span>
          ) : (
            <Button size="xs" variant="outline" disabled={disabled} onClick={onChoose}>
              {t("choose")}
            </Button>
          )}
        </div>
      </div>
      {(book.learning > 0 || book.known > 0) && (
        <>
          <div
            className="h-1.5 overflow-hidden rounded-full bg-muted"
            role="progressbar"
            aria-valuenow={percent}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-label={bookName(book, locale)}
          >
            <div className="h-full bg-primary" style={{ width: `${percent}%` }} />
          </div>
          <p className="text-xs text-muted-foreground">
            {t("progress", { learning: book.learning, known: book.known, percent })}
          </p>
        </>
      )}
    </li>
  );
}

function DailyNewCard({
  overview,
  disabled,
  onSave,
}: {
  overview: VocabOverview;
  disabled: boolean;
  onSave: (dailyNew: number | null) => void;
}) {
  const t = useTranslations("vocab.dailyNew");
  const [value, setValue] = useState(overview.daily_new?.toString() ?? "");
  const parsed = value.trim() === "" ? null : Number(value);
  const valid =
    parsed === null || (Number.isInteger(parsed) && parsed >= 0 && parsed <= DAILY_NEW_MAX);
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("title")}</CardTitle>
        <CardDescription>
          {t("description", { default: overview.daily_new_default })}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form
          className="flex items-center gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (valid) onSave(parsed);
          }}
        >
          <Input
            type="number"
            min={0}
            max={DAILY_NEW_MAX}
            className="w-24"
            aria-label={t("title")}
            aria-invalid={!valid}
            placeholder={overview.daily_new_default.toString()}
            value={value}
            onChange={(e) => setValue(e.target.value)}
          />
          <Button
            type="submit"
            size="sm"
            disabled={disabled || !valid || parsed === overview.daily_new}
          >
            {t("save")}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
