"use client";

import { ListChecks } from "lucide-react";
import { useFormatter, useLocale, useTranslations } from "next-intl";
import { useEffect, useRef, useState } from "react";

import { AiBadge } from "@/components/ai-badge";
import { CatLoading } from "@/components/brand/lingo-cat";
import { PlacementReminder } from "@/components/placement/placement-reminder";
import { useDescribeError } from "@/components/settings/use-describe-error";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorText } from "@/components/ui/error-text";
import { ApiError } from "@/lib/api";
import { kcName } from "@/lib/learner";
import {
  answerItem,
  fetchRecentSets,
  fetchSet,
  isUnfinished,
  type Item,
  openItems,
  type Origin,
  type PracticeSet,
  type Reply,
  reportItem,
  type SetBrief,
  startSet,
} from "@/lib/practice";

import { PracticeItem } from "./practice-item";
import { PracticeSummary } from "./practice-summary";

/** How often a set being generated is polled. */
export const POLL_MS = 1500;

type View =
  | { kind: "loading" }
  | { kind: "landing"; recent: SetBrief[] }
  | { kind: "set"; set: PracticeSet; current: number };

/** The item to show: the first one still open, else the last (the set is done). */
function firstOpen(set: PracticeSet): number {
  const open = openItems(set)[0];
  return open ? set.items.indexOf(open) : Math.max(0, set.items.length - 1);
}

/**
 * Grammar practice sets (P2 plan §3.7, task 35). Opened from an entry point
 * (`?from=…`, maybe `&kc=…`) it starts or continues a set at once; opened on its own it
 * shows a start button and the latest sets. A set being generated shows the hopping cat
 * until it is ready; then one item per screen, and the summary once done.
 */
export function PracticeApp({ from, kc }: { from: Origin | null; kc: string | null }) {
  const t = useTranslations("practice");
  const tCat = useTranslations("cat");
  const describe = useDescribeError();
  const [view, setView] = useState<View>({ kind: "loading" });
  const [error, setError] = useState<string | null>(null);
  const [itemError, setItemError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // A second click or key press lands before React re-renders with `busy`.
  const sending = useRef(false);
  // The answer that finished the set: show its verdict before the summary.
  const [finished, setFinished] = useState(false);

  const show = (set: PracticeSet) => setView({ kind: "set", set, current: firstOpen(set) });

  async function start(origin: Origin, kcId: string | null = null) {
    setBusy(true);
    setError(null);
    setFinished(false);
    try {
      show(await startSet(origin, kcId));
    } catch (e) {
      setError(describe(e));
    } finally {
      setBusy(false);
    }
  }

  async function open(id: string) {
    setBusy(true);
    setError(null);
    try {
      show(await fetchSet(id));
    } catch (e) {
      setError(describe(e));
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    const opened = from
      ? startSet(from, kc).then(show)
      : fetchRecentSets().then((recent) => setView({ kind: "landing", recent }));
    opened.catch((e: unknown) => {
      setError(describe(e));
      void fetchRecentSets().then(
        (recent) => setView({ kind: "landing", recent }),
        () => setView({ kind: "landing", recent: [] }),
      );
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- once, from the URL
  }, []);

  // Poll a set being generated until it is ready (or failed).
  const generatingId = view.kind === "set" && view.set.status === "generating" ? view.set.id : null;
  useEffect(() => {
    if (!generatingId) return;
    let live = true;
    const timer = setTimeout(() => {
      fetchSet(generatingId).then(
        (set) => live && show(set),
        (e: unknown) => live && setError(describe(e)),
      );
    }, POLL_MS);
    return () => {
      live = false;
      clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- re-armed by each new set state
  }, [generatingId, view]);

  function replaceItem(set: PracticeSet, item: Item): PracticeSet {
    return { ...set, items: set.items.map((i) => (i.id === item.id ? item : i)) };
  }

  async function act(run: () => Promise<{ item: Item; set_done: boolean }>) {
    if (view.kind !== "set" || sending.current) return;
    const { set, current } = view;
    sending.current = true;
    setBusy(true);
    setItemError(null);
    try {
      const { item, set_done } = await run();
      setView({ kind: "set", set: replaceItem(set, item), current });
      if (set_done) setFinished(true);
    } catch (e) {
      setItemError(describe(e));
      if (e instanceof ApiError && e.code === "not_answerable") {
        // Answered or closed elsewhere: show the set as it is now.
        await fetchSet(set.id).then(show, () => undefined);
      }
    } finally {
      sending.current = false;
      setBusy(false);
    }
  }

  async function next() {
    if (view.kind !== "set") return;
    setItemError(null);
    if (finished || openItems(view.set).length === 0) {
      setFinished(false);
      await open(view.set.id); // done: fetch the summary
      return;
    }
    setView({ ...view, current: firstOpen(view.set) });
  }

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="mx-auto flex max-w-2xl flex-col gap-3.5 p-4 md:gap-4 md:px-10 md:py-8">
        {error &&
          (view.kind !== "loading" ? (
            <ErrorText>{error}</ErrorText>
          ) : (
            <EmptyState tone="error" title={error} />
          ))}
        {view.kind === "loading" && !error && <CatLoading label={tCat("loader")} />}
        {view.kind === "landing" && (
          <Landing
            recent={view.recent}
            busy={busy}
            onStart={() => void start("practice")}
            onOpen={(id) => void open(id)}
          />
        )}
        {view.kind === "set" && view.set.status === "generating" && (
          <Card data-testid="practice-generating">
            <CardContent>
              <CatLoading
                mood="hop"
                size={72}
                label={t(`stage.${view.set.stage ?? "generating"}`)}
              />
              <p className="text-center text-xs text-muted-foreground">{t("generatingNote")}</p>
            </CardContent>
          </Card>
        )}
        {view.kind === "set" && view.set.status === "failed" && (
          <EmptyState
            tone="error"
            data-testid="practice-failed"
            title={t("failed.title")}
            description={failedReason(t, view.set.error_code)}
            action={
              <Button variant="outline" size="sm" disabled={busy} onClick={() => void start("practice")}>
                {t("failed.retry")}
              </Button>
            }
          />
        )}
        {view.kind === "set" &&
          (view.set.status === "ready" || view.set.status === "in_progress" || (view.set.status === "done" && finished)) &&
          view.set.items[view.current] && (
            <>
              {view.set.focus_kc && <FocusLine set={view.set} />}
              <PracticeItem
                key={view.set.items[view.current].id}
                item={view.set.items[view.current]}
                index={view.current}
                total={view.set.items.length}
                busy={busy}
                error={itemError}
                onAnswer={(reply: Reply, ms: number) =>
                  void act(() => answerItem(view.set.items[view.current].id, reply, ms))
                }
                onReport={() => void act(() => reportItem(view.set.items[view.current].id))}
                onNext={() => void next()}
              />
            </>
          )}
        {view.kind === "set" && view.set.status === "done" && !finished && view.set.summary && (
          <PracticeSummary set={view.set} busy={busy} onAgain={() => void start("practice")} />
        )}
      </div>
    </div>
  );
}

const FAILED_CODES = ["no_llm_configured", "generation_failed", "interrupted", "expired"] as const;

function failedReason(t: ReturnType<typeof useTranslations<"practice">>, code: string | null) {
  const known = FAILED_CODES.find((c) => c === code);
  return known ? t(`failed.${known}`) : t("failed.other");
}

function FocusLine({ set }: { set: PracticeSet }) {
  const t = useTranslations("practice");
  const locale = useLocale();
  return (
    <p className="text-sm text-muted-foreground" data-testid="practice-focus">
      {t("focus", { kc: kcName(set.focus_kc!, locale) })}
    </p>
  );
}

function Landing({
  recent,
  busy,
  onStart,
  onOpen,
}: {
  recent: SetBrief[];
  busy: boolean;
  onStart: () => void;
  onOpen: (id: string) => void;
}) {
  const t = useTranslations("practice.landing");
  const format = useFormatter();
  const locale = useLocale();
  const unfinished = recent.find((s) => isUnfinished(s.status));
  return (
    <>
      {/* Before a first set: the test makes the questions fit (Q50b); practising first is fine. */}
      <PlacementReminder reasons={["never", "resume"]} where="practice" />
      <Card data-testid="practice-landing">
        <CardHeader>
          <CardTitle>
            <h1>{t("title")}</h1>
          </CardTitle>
          <CardDescription>{t("description")}</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4 text-sm">
          <p className="text-muted-foreground">{t("how")}</p>
          <div className="flex items-center gap-2">
            <Button disabled={busy} onClick={onStart} data-testid="practice-start">
              {unfinished ? t("continue") : t("start")}
            </Button>
            <AiBadge feature={["practice_set", "practice_grade"]} />
          </div>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>{t("recent")}</CardTitle>
        </CardHeader>
        <CardContent>
          {recent.length === 0 ? (
            <EmptyState title={t("none")} />
          ) : (
            <ul className="flex flex-col divide-y text-sm" aria-label={t("recent")}>
              {recent.map((s) => (
                <li key={s.id} className="flex items-center gap-3 py-2.5" data-testid="practice-recent">
                  <ListChecks aria-hidden className="size-4 shrink-0 text-muted-foreground" />
                  <span className="flex min-w-0 flex-1 flex-col">
                    <span className="truncate font-[550]">
                      {s.focus_kc ? kcName(s.focus_kc, locale) : t("mixed")}
                    </span>
                    <span className="text-xs text-muted-foreground">
                      {format.dateTime(new Date(s.created_at), { dateStyle: "medium", timeStyle: "short" })}
                    </span>
                  </span>
                  {s.status === "done" ? (
                    <span className="text-xs text-muted-foreground tabular-nums">
                      {t("score", { correct: s.correct, total: s.answered })}
                    </span>
                  ) : isUnfinished(s.status) ? (
                    <Button size="sm" variant="outline" disabled={busy} onClick={() => onOpen(s.id)}>
                      {t("resume", { answered: s.answered, total: s.total })}
                    </Button>
                  ) : (
                    <span className="text-xs text-muted-foreground">{t("failed")}</span>
                  )}
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </>
  );
}
