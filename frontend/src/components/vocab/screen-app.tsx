"use client";

import { BookCheck, Check } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useState } from "react";

import { useDescribeError } from "@/components/settings/use-describe-error";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";
import { fetchScreenBatch, type ScreenResult, submitScreen, type Word } from "@/lib/vocab";

import { PlacementKnown } from "./placement-known";

type State =
  | { kind: "loading" }
  | { kind: "noBook" }
  | { kind: "batch"; words: Word[]; known: Set<number> }
  | { kind: "result"; result: ScreenResult };

/**
 * Known-word screening (ADR 0011 §5): tick the words you know in a batch spread over the
 * book's next words; they are never scheduled. Unticked words come later as new words.
 */
export function ScreenApp() {
  const t = useTranslations("vocab.screen");
  const describe = useDescribeError();
  const [state, setState] = useState<State>({ kind: "loading" });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(
    () =>
      fetchScreenBatch().then(
        ({ words }) => setState({ kind: "batch", words, known: new Set() }),
        (e: unknown) => {
          if (e instanceof ApiError && e.code === "no_book") setState({ kind: "noBook" });
          else setError(describe(e));
        },
      ),
    // eslint-disable-next-line react-hooks/exhaustive-deps -- describe is stable enough
    [],
  );

  useEffect(() => {
    void load();
  }, [load]);

  function next() {
    setError(null);
    setState({ kind: "loading" });
    void load();
  }

  function toggle(id: number) {
    if (state.kind !== "batch") return;
    const known = new Set(state.known);
    if (!known.delete(id)) known.add(id);
    setState({ ...state, known });
  }

  async function submit() {
    if (state.kind !== "batch") return;
    setBusy(true);
    setError(null);
    try {
      const result = await submitScreen(
        state.words.map((w) => w.id),
        [...state.known],
      );
      setState({ kind: "result", result });
    } catch (e) {
      setError(describe(e));
    } finally {
      setBusy(false);
    }
  }

  const back = (
    <Link href="/vocab" className={buttonVariants({ size: "sm", variant: "outline" })}>
      {t("back")}
    </Link>
  );

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="mx-auto flex max-w-5xl flex-col gap-3.5 p-4 md:gap-4 md:px-10 md:py-8">
        <div className="flex flex-col gap-1">
          <h1 className="flex flex-wrap items-baseline gap-x-3 text-[26px] font-bold tracking-tight">
            {t("title")}
            {state.kind === "batch" && state.words.length > 0 && (
              <span className="text-[13px] font-normal tracking-normal text-muted-foreground">
                {t("hint")}
              </span>
            )}
          </h1>
          <p className="text-sm text-muted-foreground">{t("description")}</p>
        </div>
        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}
        {state.kind !== "noBook" && <PlacementKnown quiet onChange={next} />}
        {state.kind === "noBook" && (
          <Card>
            <EmptyState icon={BookCheck} title={t("noBook")} action={back} />
          </Card>
        )}
        {state.kind === "batch" && state.words.length === 0 && (
          <Card>
            <EmptyState icon={BookCheck} title={t("finished")} action={back} />
          </Card>
        )}
        {state.kind === "batch" && state.words.length > 0 && (
          <>
            <ul className="grid grid-cols-2 gap-2 sm:grid-cols-3 md:grid-cols-5">
              {state.words.map((w) => {
                const known = state.known.has(w.id);
                return (
                  <li key={w.id}>
                    <button
                      type="button"
                      aria-pressed={known}
                      onClick={() => toggle(w.id)}
                      lang="en"
                      className={cn(
                        "flex h-10 w-full items-center justify-center gap-1.5 rounded-lg border px-2 text-sm transition-colors outline-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring",
                        known
                          ? "border-primary bg-primary text-primary-foreground"
                          : "bg-card hover:bg-muted",
                      )}
                    >
                      <span className="truncate">{w.word}</span>
                      {known && <Check aria-hidden className="size-3.5 shrink-0" />}
                    </button>
                  </li>
                );
              })}
            </ul>
            <div className="sticky bottom-0 flex flex-wrap items-center gap-2 rounded-xl border bg-card px-4 py-3 shadow-md">
              <span className="text-[13px]" data-testid="screen-count">
                {t.rich("count", {
                  known: state.known.size,
                  total: state.words.length,
                  b: (chunks) => <b className="font-semibold">{chunks}</b>,
                })}
              </span>
              <Button className="ml-auto" disabled={busy} onClick={() => void submit()}>
                {t("submit")}
              </Button>
            </div>
          </>
        )}
        {state.kind === "result" && (
          <Card className="w-full max-w-xl self-center">
            <CardHeader>
              <CardTitle>{t("title")}</CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col items-center gap-3 pb-2 text-center">
              <div className="flex flex-col gap-1" data-testid="screen-result">
                <p className="text-lg font-bold">
                  {t("result", { known: state.result.known, shown: state.result.shown })}
                </p>
                {state.result.skipped_ahead && (
                  <p className="text-sm text-muted-foreground">{t("skipped")}</p>
                )}
              </div>
              <div className="flex gap-2">
                <Button size="sm" onClick={next}>
                  {t("next")}
                </Button>
                {back}
              </div>
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  );
}
