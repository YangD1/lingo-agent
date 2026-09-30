"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useState } from "react";

import { useDescribeError } from "@/components/settings/use-describe-error";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
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
      <div className="mx-auto flex max-w-3xl flex-col gap-6 p-4 md:p-8">
        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}
        {state.kind !== "noBook" && <PlacementKnown quiet onChange={next} />}
        <Card>
          <CardHeader>
            <CardTitle>{t("title")}</CardTitle>
            <CardDescription>{t("description")}</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            {state.kind === "noBook" && (
              <>
                <p className="text-sm">{t("noBook")}</p>
                <div>{back}</div>
              </>
            )}
            {state.kind === "batch" && state.words.length === 0 && (
              <>
                <p className="text-sm">{t("finished")}</p>
                <div>{back}</div>
              </>
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
                          className={cn(
                            "w-full truncate rounded-lg border px-2 py-2 text-sm transition-colors",
                            known
                              ? "border-primary bg-primary text-primary-foreground"
                              : "hover:bg-muted",
                          )}
                        >
                          {w.word}
                        </button>
                      </li>
                    );
                  })}
                </ul>
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-sm text-muted-foreground" data-testid="screen-count">
                    {t("count", { known: state.known.size, total: state.words.length })}
                  </span>
                  <Button
                    className="ml-auto"
                    size="sm"
                    disabled={busy}
                    onClick={() => void submit()}
                  >
                    {t("submit")}
                  </Button>
                </div>
              </>
            )}
            {state.kind === "result" && (
              <>
                <p className="text-sm" data-testid="screen-result">
                  {t("result", { known: state.result.known, shown: state.result.shown })}
                  {state.result.skipped_ahead && ` ${t("skipped")}`}
                </p>
                <div className="flex gap-2">
                  <Button size="sm" onClick={next}>
                    {t("next")}
                  </Button>
                  {back}
                </div>
              </>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
