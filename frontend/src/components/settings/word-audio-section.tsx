"use client";

import { useFormatter, useLocale, useTranslations } from "next-intl";
import { useCallback, useEffect, useState } from "react";

import { AiBadge } from "@/components/ai-badge";
import { Button } from "@/components/ui/button";
import { Callout } from "@/components/ui/callout";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ErrorText } from "@/components/ui/error-text";
import { InlineConfirm } from "@/components/ui/inline-confirm";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ProgressBar } from "@/components/ui/progress";
import { ApiError, api } from "@/lib/api";
import type {
  WordAudio,
  WordAudioAccent,
  WordAudioBook,
  WordAudioEstimate,
  WordAudioJob,
} from "@/lib/types";

import { useDescribeError } from "./use-describe-error";

const ACCENTS: WordAudioAccent[] = ["en-US", "en-GB"];
// How often the page asks for progress while a job runs.
export const WORD_AUDIO_POLL_MS = 3000;

/**
 * Word pronunciations generated ahead of time (ADR 0028 §4), for tenant owners/admins:
 * pick a book and accents, see the words, characters, size and cost, then start; follow
 * the progress, pause, resume or cancel; delete a book's audio or that in old voices.
 */
export function WordAudioSection() {
  const t = useTranslations("settings.wordAudio");
  const describe = useDescribeError();
  // null: not loaded yet, or not a tenant manager (403): the card stays hidden.
  const [state, setState] = useState<WordAudio | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [planning, setPlanning] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(() => {
    api<WordAudio>("/tenant/word-audio").then(
      (s) => {
        setState(s);
        setError(null);
      },
      (e: unknown) => {
        if (!(e instanceof ApiError && e.status === 403)) setError(describe(e));
      },
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps -- describe changes with locale only
  }, []);
  useEffect(() => load(), [load]);

  const running = state?.job?.status === "running";
  useEffect(() => {
    if (!running) return;
    const timer = setInterval(load, WORD_AUDIO_POLL_MS);
    return () => clearInterval(timer);
  }, [running, load]);

  async function act(run: () => Promise<unknown>) {
    setBusy(true);
    setNotice(null);
    try {
      await run();
      setError(null);
    } catch (e) {
      setError(describe(e));
    } finally {
      setBusy(false);
      load();
    }
  }

  if (!state && !error) return null;
  const active = state?.job && (state.job.status === "running" || state.job.status === "paused");

  return (
    <Card id="word-audio" className="scroll-mt-14 lg:scroll-mt-4">
      <CardHeader>
        <CardTitle className="flex items-center gap-1.5">
          {t("title")}
          <AiBadge feature="word_audio_prefetch" />
        </CardTitle>
        <CardDescription>{t("description")}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {error && <ErrorText>{error}</ErrorText>}
        {state && !state.available && <Callout>{t("unavailable")}</Callout>}
        {state?.job && (
          <JobPanel
            job={state.job}
            book={state.books.find((b) => b.book_id === state.job?.book_id)}
            busy={busy}
            onAction={(action) =>
              void act(() => api(`/tenant/word-audio/jobs/current/${action}`, { method: "POST" }))
            }
          />
        )}
        {state && (
          <ul className="flex flex-col divide-y text-sm">
            {state.books.map((book) => (
              <li key={book.book_id} className="flex flex-col gap-2 py-2.5">
                <BookRow
                  book={book}
                  canStart={state.available && !active && planning === null}
                  canDelete={!active && (book.made["en-US"] > 0 || book.made["en-GB"] > 0)}
                  onPlan={() => setPlanning(book.book_id)}
                  onDelete={() =>
                    void act(async () => {
                      const r = await api<{ deleted: number }>(
                        `/tenant/word-audio?book_id=${encodeURIComponent(book.book_id)}`,
                        { method: "DELETE" },
                      );
                      setNotice(t("deleted", { count: r.deleted }));
                    })
                  }
                />
                {planning === book.book_id && (
                  <StartForm
                    book={book}
                    onCancel={() => setPlanning(null)}
                    onStarted={() => {
                      setPlanning(null);
                      load();
                    }}
                  />
                )}
              </li>
            ))}
          </ul>
        )}
        {state && <Storage state={state} active={Boolean(active)} busy={busy} onDeleteOld={() =>
          void act(async () => {
            const r = await api<{ deleted: number }>("/tenant/word-audio?old=true", {
              method: "DELETE",
            });
            setNotice(t("deleted", { count: r.deleted }));
          })
        } />}
        {notice && <p className="text-sm text-muted-foreground" role="status">{notice}</p>}
      </CardContent>
    </Card>
  );
}

function useBookName(): (book: WordAudioBook | undefined, fallback: string) => string {
  const locale = useLocale();
  return (book, fallback) =>
    book ? (locale.startsWith("zh") ? book.name_zh : book.name_en) : fallback;
}

function useMegabytes(): (bytes: number) => string {
  const format = useFormatter();
  return (bytes) => format.number(bytes / 1024 / 1024, { maximumFractionDigits: 1 });
}

function useMoney(): (amount: number, currency: string | null) => string {
  const format = useFormatter();
  return (amount, currency) =>
    `${format.number(amount, { maximumFractionDigits: amount < 1 ? 3 : 2 })}${currency ? ` ${currency}` : ""}`;
}

function JobPanel({
  job,
  book,
  busy,
  onAction,
}: {
  job: WordAudioJob;
  book: WordAudioBook | undefined;
  busy: boolean;
  onAction: (action: "pause" | "resume" | "cancel") => void;
}) {
  const t = useTranslations("settings.wordAudio");
  const format = useFormatter();
  const bookName = useBookName();
  const money = useMoney();
  const active = job.status === "running" || job.status === "paused";
  return (
    <section aria-labelledby="word-audio-job" className="flex flex-col gap-2 rounded-lg border p-3">
      <h3 id="word-audio-job" className="text-sm font-semibold">
        {t("jobTitle", { book: bookName(book, job.book_id), status: t(`status.${job.status}`) })}
      </h3>
      <ProgressBar value={job.total ? job.done / job.total : 1} />
      <p className="text-sm">
        {t("progress", {
          done: format.number(job.done),
          total: format.number(job.total),
          failed: job.failed,
        })}
      </p>
      <p className="text-sm text-muted-foreground">
        {t("sent", { characters: format.number(job.characters) })}
        {job.cost !== null && ` · ${t("costSoFar", { cost: money(job.cost, job.currency) })}`}
      </p>
      {job.error && <ErrorText>{t("pausedBecause", { reason: job.error })}</ErrorText>}
      {job.failed > 0 && !active && <p className="text-sm text-muted-foreground">{t("retryHint")}</p>}
      {active && (
        <div className="flex flex-wrap gap-2">
          {job.status === "running" ? (
            <Button size="sm" variant="outline" disabled={busy} onClick={() => onAction("pause")}>
              {t("pause")}
            </Button>
          ) : (
            <Button size="sm" variant="outline" disabled={busy} onClick={() => onAction("resume")}>
              {t("resume")}
            </Button>
          )}
          <InlineConfirm
            question={t("cancelQuestion")}
            confirmLabel={t("cancelJob")}
            onConfirm={() => onAction("cancel")}
          >
            {(ask) => (
              <Button size="sm" variant="ghost" disabled={busy} onClick={ask}>
                {t("cancelJob")}
              </Button>
            )}
          </InlineConfirm>
        </div>
      )}
    </section>
  );
}

function BookRow({
  book,
  canStart,
  canDelete,
  onPlan,
  onDelete,
}: {
  book: WordAudioBook;
  canStart: boolean;
  canDelete: boolean;
  onPlan: () => void;
  onDelete: () => void;
}) {
  const t = useTranslations("settings.wordAudio");
  const format = useFormatter();
  const bookName = useBookName();
  const name = bookName(book, book.book_id);
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
      <div className="min-w-0 flex-1">
        <p className="font-medium">{name}</p>
        <p className="text-muted-foreground">
          {t("bookMade", {
            words: format.number(book.words),
            us: format.number(book.made["en-US"]),
            gb: format.number(book.made["en-GB"]),
          })}
        </p>
      </div>
      <Button size="sm" variant="outline" disabled={!canStart} onClick={onPlan} aria-label={t("planFor", { book: name })}>
        {t("plan")}
      </Button>
      {canDelete && (
        <InlineConfirm question={t("deleteBookQuestion")} onConfirm={onDelete}>
          {(ask) => (
            <Button size="sm" variant="ghost" onClick={ask} aria-label={t("deleteFor", { book: name })}>
              {t("delete")}
            </Button>
          )}
        </InlineConfirm>
      )}
    </div>
  );
}

function StartForm({
  book,
  onCancel,
  onStarted,
}: {
  book: WordAudioBook;
  onCancel: () => void;
  onStarted: () => void;
}) {
  const t = useTranslations("settings.wordAudio");
  const format = useFormatter();
  const describe = useDescribeError();
  const megabytes = useMegabytes();
  const money = useMoney();
  const [accents, setAccents] = useState<WordAudioAccent[]>(ACCENTS);
  const [price, setPrice] = useState<string | null>(null); // null: not prefilled yet
  const [currency, setCurrency] = useState("");
  const [rate, setRate] = useState<string | null>(null);
  const [estimate, setEstimate] = useState<WordAudioEstimate | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);

  const priceValue = price === null || price.trim() === "" ? null : Number(price);
  const priceValid = priceValue === null || (Number.isFinite(priceValue) && priceValue >= 0);
  const rateValue = Number(rate);
  const rateValid = Number.isInteger(rateValue) && rateValue >= 1 && rateValue <= 600;

  useEffect(() => {
    if (accents.length === 0 || !priceValid) return;
    const params = new URLSearchParams({ book_id: book.book_id });
    for (const accent of accents) params.append("accents", accent);
    if (priceValue !== null) params.set("price_per_million", String(priceValue));
    let live = true;
    api<WordAudioEstimate>(`/tenant/word-audio/estimate?${params}`).then(
      (e) => {
        if (!live) return;
        setEstimate(e);
        setError(null);
        // The first estimate suggests a pace and, for Azure, a price (Q55d, Q55e).
        setRate((r) => r ?? String(e.requests_per_minute));
        if (price === null && e.suggested_price !== null) {
          setPrice(String(e.suggested_price));
          setCurrency("USD");
        }
      },
      (e: unknown) => live && setError(describe(e)),
    );
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- re-estimate on these inputs only
  }, [book.book_id, accents.join(), priceValue, priceValid]);

  async function start() {
    setStarting(true);
    try {
      await api("/tenant/word-audio/jobs", {
        method: "POST",
        json: {
          book_id: book.book_id,
          accents: accents.filter((a) => estimate?.voices[a]),
          requests_per_minute: rateValue,
          price_per_million: priceValue,
          currency: currency.trim() || null,
        },
      });
      onStarted();
    } catch (e) {
      setError(describe(e));
      setStarting(false);
    }
  }

  const toMake = estimate ? estimate.pieces - estimate.existing : 0;
  const minutes = estimate && rateValid ? Math.ceil(toMake / rateValue) : null;
  const readable = estimate ? accents.filter((a) => estimate.voices[a]) : [];

  return (
    <form
      aria-label={t("formLabel")}
      className="flex flex-col gap-3 rounded-lg bg-muted/50 p-3"
      onSubmit={(e) => {
        e.preventDefault();
        void start();
      }}
    >
      <fieldset className="flex flex-wrap gap-4">
        <legend className="mb-1.5 text-[13px] font-medium">{t("accents")}</legend>
        {ACCENTS.map((accent) => (
          <label key={accent} className="flex items-center gap-1.5">
            <input
              type="checkbox"
              checked={accents.includes(accent)}
              onChange={(e) =>
                setAccents((all) =>
                  e.target.checked
                    ? ACCENTS.filter((a) => a === accent || all.includes(a))
                    : all.filter((a) => a !== accent),
                )
              }
            />
            {t(`accent.${accent}`)}
            {estimate?.voices[accent] && (
              <span className="text-muted-foreground">
                {t("voiceOf", { voice: estimate.voices[accent].voice })}
              </span>
            )}
          </label>
        ))}
      </fieldset>
      <div className="flex flex-wrap items-end gap-3">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="word-audio-price">{t("price")}</Label>
          <Input
            id="word-audio-price"
            type="number"
            inputMode="decimal"
            min={0}
            step="any"
            value={price ?? ""}
            aria-invalid={!priceValid}
            onChange={(e) => setPrice(e.target.value)}
            className="w-32"
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="word-audio-currency">{t("currency")}</Label>
          <Input
            id="word-audio-currency"
            maxLength={8}
            value={currency}
            onChange={(e) => setCurrency(e.target.value)}
            className="w-24"
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="word-audio-rate">{t("rate")}</Label>
          <Input
            id="word-audio-rate"
            type="number"
            inputMode="numeric"
            min={1}
            max={600}
            value={rate ?? ""}
            aria-invalid={!rateValid}
            onChange={(e) => setRate(e.target.value)}
            className="w-28"
          />
        </div>
      </div>
      <p className="text-[13px] text-muted-foreground">{t("priceHint")}</p>
      {estimate && (
        <div className="flex flex-col gap-1 text-sm" role="status">
          <p>
            {t("estimate", {
              words: format.number(estimate.words),
              pieces: format.number(estimate.pieces),
              existing: format.number(estimate.existing),
              toMake: format.number(toMake),
            })}
          </p>
          <p>
            {t("estimateCost", {
              characters: format.number(estimate.characters),
              megabytes: megabytes(estimate.bytes),
              minutes: minutes ?? "—",
            })}
            {estimate.cost !== null && ` · ${t("cost", { cost: money(estimate.cost, currency.trim() || null) })}`}
          </p>
          {estimate.missing.length > 0 && (
            <p className="text-muted-foreground">
              {t("missing", { accents: estimate.missing.map((a) => t(`accent.${a}`)).join("、") })}
            </p>
          )}
        </div>
      )}
      {error && <ErrorText>{error}</ErrorText>}
      <div className="flex gap-2">
        <Button
          type="submit"
          disabled={!estimate || readable.length === 0 || !priceValid || !rateValid || starting}
        >
          {t("start")}
        </Button>
        <Button type="button" variant="ghost" onClick={onCancel}>
          {t("cancel")}
        </Button>
      </div>
    </form>
  );
}

function Storage({
  state,
  active,
  busy,
  onDeleteOld,
}: {
  state: WordAudio;
  active: boolean;
  busy: boolean;
  onDeleteOld: () => void;
}) {
  const t = useTranslations("settings.wordAudio");
  const format = useFormatter();
  const megabytes = useMegabytes();
  return (
    <div className="flex flex-col gap-1.5 border-t pt-3 text-sm">
      <p>{t("storage", { count: format.number(state.count), megabytes: megabytes(state.bytes) })}</p>
      {state.old_count > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-muted-foreground">
            {t("old", { count: format.number(state.old_count), megabytes: megabytes(state.old_bytes) })}
          </span>
          {!active && (
            <InlineConfirm question={t("deleteOldQuestion")} onConfirm={onDeleteOld}>
              {(ask) => (
                <Button size="sm" variant="ghost" disabled={busy} onClick={ask}>
                  {t("deleteOld")}
                </Button>
              )}
            </InlineConfirm>
          )}
        </div>
      )}
    </div>
  );
}
