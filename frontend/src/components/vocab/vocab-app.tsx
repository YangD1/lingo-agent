"use client";

import { Bookmark, Minus, Play, Plus, Sparkles } from "lucide-react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { useCallback, useEffect, useState } from "react";

import { useDescribeError } from "@/components/settings/use-describe-error";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Callout } from "@/components/ui/callout";
import { ProgressBar } from "@/components/ui/progress";
import { Tag } from "@/components/ui/tag";
import { ErrorText } from "@/components/ui/error-text";
import { EmptyState } from "@/components/ui/empty-state";
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
  const tNav = useTranslations("nav");
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
      <div className="mx-auto flex max-w-3xl flex-col gap-3.5 p-4 md:gap-4 md:px-10 md:py-8">
        <h1 className="text-[26px] font-bold tracking-tight max-md:sr-only">{tNav("vocab")}</h1>
        {error &&
          (overview ? (
            <ErrorText>{error}</ErrorText>
          ) : (
            // Nothing loaded: the whole area failed, so the big oops cat.
            <EmptyState tone="error" title={error} />
          ))}
        {overview && today && (
          <Card data-testid="vocab-today">
            <CardHeader>
              <CardTitle>{t("today.title")}</CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col gap-4">
              <div className="flex flex-wrap items-center gap-x-4 gap-y-3">
                <div className="flex min-w-0 flex-1 flex-col gap-1">
                  <p className="text-xs text-muted-foreground">
                    {current
                      ? t("today.book", { book: bookName(current, locale) })
                      : t("today.noBook")}
                  </p>
                  <p data-testid="today-counts" className="flex flex-col">
                    <span className="text-lg font-bold tracking-tight md:text-xl">
                      {t("today.countsMain", {
                        reviews: today.reviews_due,
                        left: today.new_left,
                      })}
                    </span>
                    <span className="text-xs text-muted-foreground tabular-nums">
                      {t("today.countsStarted", {
                        started: today.new_started,
                        limit: today.new_limit,
                      })}
                    </span>
                  </p>
                </div>
                {work > 0 && (
                  <Link href="/vocab/review" className={buttonVariants({ size: "lg" })}>
                    <Play />
                    {t("today.start")}
                  </Link>
                )}
              </div>
              {work === 0 && <p className="text-sm text-muted-foreground">{t("today.done")}</p>}
              {current && !overview.screened && (
                <Callout tone="brand" icon={<Sparkles />}>
                  {t("today.screenHint")}
                </Callout>
              )}
              <div className="flex flex-wrap gap-2 border-t pt-3">
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
                  <Bookmark />
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
  const started = book.learning > 0 || book.known > 0;
  return (
    <li className="flex items-center gap-3 py-3" data-testid={`book-${book.id}`}>
      <div className="flex min-w-0 flex-1 flex-col gap-1.5">
        <p className="flex items-baseline gap-2">
          <span className="text-sm font-[550]">{bookName(book, locale)}</span>
          <span className="font-mono text-xs text-muted-foreground">
            {t("size", { total: book.total })}
          </span>
        </p>
        {started ? (
          <span
            role="progressbar"
            aria-valuenow={percent}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-label={bookName(book, locale)}
            className="max-w-72"
          >
            <ProgressBar value={percent / 100} thin />
          </span>
        ) : (
          <ProgressBar value={0} thin className="max-w-72" />
        )}
        <p className="text-xs text-muted-foreground">
          {started
            ? t("progress", { learning: book.learning, known: book.known, percent })
            : t("notStarted")}
        </p>
      </div>
      {current ? (
        <Tag variant="brand">{t("current")}</Tag>
      ) : (
        <Button size="sm" variant="outline" disabled={disabled} onClick={onChoose}>
          {t("choose")}
        </Button>
      )}
    </li>
  );
}

const STEP = 5;

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
  const step = (delta: number) => {
    const from = valid ? (parsed ?? overview.daily_new_default) : overview.daily_new_default;
    setValue(String(Math.max(0, Math.min(DAILY_NEW_MAX, from + delta))));
  };
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
          <div className="flex h-10 items-stretch overflow-hidden rounded-lg border border-input bg-card md:h-9">
            <button
              type="button"
              aria-label={t("fewer")}
              onClick={() => step(-STEP)}
              className="flex w-9 items-center justify-center text-muted-foreground hover:bg-muted hover:text-foreground"
            >
              <Minus className="size-4" />
            </button>
            <input
              type="number"
              min={0}
              max={DAILY_NEW_MAX}
              aria-label={t("title")}
              aria-invalid={!valid}
              placeholder={overview.daily_new_default.toString()}
              value={value}
              onChange={(e) => setValue(e.target.value)}
              className="w-14 border-x bg-transparent text-center font-mono text-sm outline-none [appearance:textfield] focus-visible:bg-muted/50 aria-invalid:text-destructive [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none"
            />
            <button
              type="button"
              aria-label={t("more")}
              onClick={() => step(STEP)}
              className="flex w-9 items-center justify-center text-muted-foreground hover:bg-muted hover:text-foreground"
            >
              <Plus className="size-4" />
            </button>
          </div>
          <Button
            type="submit"
            variant="outline"
            disabled={disabled || !valid || parsed === overview.daily_new}
          >
            {t("save")}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
