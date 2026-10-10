"use client";

import { ChevronDownIcon, MessagesSquareIcon, MicOffIcon, PlayIcon, Trash2 } from "lucide-react";
import { useFormatter, useLocale, useTranslations } from "next-intl";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { AiBadge } from "@/components/ai-badge";
import { CatLoading } from "@/components/brand/lingo-cat";
import { useDescribeError } from "@/components/settings/use-describe-error";
import { Button, buttonVariants } from "@/components/ui/button";
import { Callout } from "@/components/ui/callout";
import { ErrorText } from "@/components/ui/error-text";
import { InlineConfirm } from "@/components/ui/inline-confirm";
import { Tag } from "@/components/ui/tag";
import {
  deleteSession,
  fetchScenarios,
  fetchSessions,
  type Scenario,
  scenarioGoal,
  scenarioTitle,
  type Scenarios,
  type SpeakingSession,
  startSession,
} from "@/lib/speaking";
import { useServerSpeech } from "@/lib/speech";

/**
 * Speaking practice (task 59.2, ADR 0029 §6): the last practice still open, free talk and
 * the scenarios (those for my level first, the rest folded), and past practices with
 * their summaries. Picking one starts a new practice: the tutor speaks first.
 */
export function SpeakingList() {
  const t = useTranslations("speaking.list");
  const locale = useLocale();
  const router = useRouter();
  const describe = useDescribeError();
  const { asr } = useServerSpeech();
  const [scenarios, setScenarios] = useState<Scenarios | null>(null);
  const [sessions, setSessions] = useState<SpeakingSession[] | null>(null);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [starting, setStarting] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchScenarios().then(setScenarios, (e: unknown) => setError(describe(e)));
    fetchSessions().then(
      (page) => {
        setSessions(page.items);
        setCursor(page.next_before);
      },
      (e: unknown) => setError(describe(e)),
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps -- once
  }, []);

  async function start(scenarioId: string | null) {
    if (starting !== null) return;
    setStarting(scenarioId ?? "");
    setError(null);
    try {
      const session = await startSession(scenarioId, locale);
      router.push(`/speaking/${session.id}`);
    } catch (e) {
      setError(describe(e));
      setStarting(null);
    }
  }

  async function more() {
    if (!cursor || loadingMore) return;
    setLoadingMore(true);
    try {
      const page = await fetchSessions(cursor);
      setSessions((prev) => [...(prev ?? []), ...page.items]);
      setCursor(page.next_before);
    } catch (e) {
      setError(describe(e));
    } finally {
      setLoadingMore(false);
    }
  }

  async function remove(id: string) {
    try {
      await deleteSession(id);
      setSessions((prev) => prev?.filter((s) => s.id !== id) ?? null);
    } catch (e) {
      setError(describe(e));
    }
  }

  const byId = new Map(scenarios?.scenarios.map((s) => [s.id, s]));
  const open = sessions?.find((s) => s.status === "active");
  const suits = scenarios?.scenarios.filter((s) => s.suits) ?? [];
  const others = scenarios?.scenarios.filter((s) => !s.suits) ?? [];

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="mx-auto flex max-w-2xl flex-col gap-3.5 p-4 md:gap-4 md:px-10 md:py-8">
        <header className="flex min-w-0 flex-col gap-1">
          <h1 className="text-xl font-semibold">{t("title")}</h1>
          <p className="flex flex-wrap items-center gap-1.5 text-sm text-muted-foreground">
            {t("description")}
            <AiBadge feature={["speaking_start", "speaking_turn"]} />
          </p>
        </header>

        {asr === false && (
          <Callout
            tone="warning"
            icon={<MicOffIcon aria-hidden />}
            data-testid="speaking-no-asr"
            action={
              <Link href="/settings" className={buttonVariants({ size: "sm", variant: "outline" })}>
                {t("noAsrAction")}
              </Link>
            }
          >
            {t("noAsr")}
          </Callout>
        )}
        {error && <ErrorText>{error}</ErrorText>}

        {open && (
          <section aria-label={t("continue")} className="flex flex-col gap-2">
            <h2 className="text-sm font-semibold">{t("continue")}</h2>
            <Link
              href={`/speaking/${open.id}`}
              data-testid="speaking-continue"
              className="flex items-center gap-3 rounded-xl border border-primary/40 bg-brand-soft px-4 py-3 outline-none transition-colors hover:bg-brand-soft/70 focus-visible:outline-2 focus-visible:outline-ring"
            >
              <PlayIcon aria-hidden className="size-4 shrink-0 text-brand-soft-foreground" />
              <span className="flex min-w-0 flex-col gap-0.5">
                <span className="font-[550]">{sessionTitle(open, byId, locale, t("freeTalk"))}</span>
                <span className="text-xs text-muted-foreground">{open.turns ? t("turns", { n: open.turns }) : t("noTurns")}</span>
              </span>
            </Link>
          </section>
        )}

        <section aria-label={t("scenarios")} className="flex flex-col gap-2">
          <h2 className="text-sm font-semibold">{t("scenarios")}</h2>
          {scenarios === null && !error && <CatLoading size={48} label={t("loading")} />}
          {scenarios && (
            <ul className="grid gap-2 sm:grid-cols-2">
              <li>
                <ScenarioCard
                  title={t("freeTalk")}
                  goal={t("freeTalkGoal")}
                  icon
                  busy={starting === ""}
                  disabled={starting !== null}
                  onStart={() => void start(null)}
                />
              </li>
              {suits.map((s) => (
                <li key={s.id}>
                  <ScenarioCard
                    scenario={s}
                    title={scenarioTitle(s, locale)}
                    goal={scenarioGoal(s, locale)}
                    busy={starting === s.id}
                    disabled={starting !== null}
                    onStart={() => void start(s.id)}
                  />
                </li>
              ))}
            </ul>
          )}
          {others.length > 0 && (
            <details className="group">
              <summary className="flex cursor-pointer list-none items-center gap-1 py-1 text-sm text-muted-foreground hover:text-foreground">
                <ChevronDownIcon aria-hidden className="size-4 transition-transform group-open:rotate-180" />
                {t("otherLevels", { n: others.length, level: scenarios?.level ?? "" })}
              </summary>
              <ul className="mt-2 grid gap-2 sm:grid-cols-2">
                {others.map((s) => (
                  <li key={s.id}>
                    <ScenarioCard
                      scenario={s}
                      title={scenarioTitle(s, locale)}
                      goal={scenarioGoal(s, locale)}
                      busy={starting === s.id}
                      disabled={starting !== null}
                      onStart={() => void start(s.id)}
                    />
                  </li>
                ))}
              </ul>
            </details>
          )}
        </section>

        {sessions && sessions.length > 0 && (
          <section aria-label={t("history")} className="flex flex-col gap-2">
            <h2 className="text-sm font-semibold">{t("history")}</h2>
            <ul className="flex flex-col gap-2">
              {sessions.map((s) => (
                <li key={s.id}>
                  <HistoryRow
                    session={s}
                    title={sessionTitle(s, byId, locale, t("freeTalk"))}
                    onDelete={() => void remove(s.id)}
                  />
                </li>
              ))}
            </ul>
            {cursor && (
              <Button variant="ghost" disabled={loadingMore} onClick={() => void more()} className="self-center">
                {loadingMore ? t("loadingMore") : t("more")}
              </Button>
            )}
          </section>
        )}
      </div>
    </div>
  );
}

function sessionTitle(
  session: SpeakingSession,
  scenarios: Map<string, Scenario>,
  locale: string,
  freeTalk: string,
): string {
  const scenario = session.scenario_id ? scenarios.get(session.scenario_id) : undefined;
  return scenario ? scenarioTitle(scenario, locale) : freeTalk;
}

function ScenarioCard({
  scenario,
  title,
  goal,
  icon = false,
  busy,
  disabled,
  onStart,
}: {
  scenario?: Scenario;
  title: string;
  goal: string;
  icon?: boolean;
  busy: boolean;
  disabled: boolean;
  onStart: () => void;
}) {
  const t = useTranslations("speaking.list");
  return (
    <button
      type="button"
      onClick={onStart}
      disabled={disabled}
      aria-busy={busy}
      data-testid={`speaking-scenario-${scenario?.id ?? "free"}`}
      className="flex h-full w-full flex-col items-start gap-1.5 rounded-xl border bg-card px-4 py-3 text-left outline-none transition-colors hover:bg-accent/50 focus-visible:outline-2 focus-visible:outline-ring disabled:opacity-60"
    >
      <span className="flex w-full items-center gap-2">
        {icon && <MessagesSquareIcon aria-hidden className="size-4 shrink-0 text-muted-foreground" />}
        <span className="min-w-0 flex-1 font-[550] leading-snug">{title}</span>
        {scenario && (
          <Tag variant="outline">
            {scenario.levels[0] === scenario.levels[1]
              ? scenario.levels[0]
              : `${scenario.levels[0]}–${scenario.levels[1]}`}
          </Tag>
        )}
      </span>
      <span className="text-sm text-muted-foreground">{busy ? t("starting") : goal}</span>
      {scenario && scenario.target_expressions.length > 0 && (
        <span lang="en" className="flex flex-wrap gap-1">
          {scenario.target_expressions.slice(0, 3).map((e) => (
            <Tag key={e}>{e}</Tag>
          ))}
        </span>
      )}
    </button>
  );
}

function HistoryRow({
  session: s,
  title,
  onDelete,
}: {
  session: SpeakingSession;
  title: string;
  onDelete: () => void;
}) {
  const t = useTranslations("speaking.list");
  const format = useFormatter();
  const minutes = Math.round(s.spoken_seconds / 6) / 10;
  return (
    <div
      data-testid="speaking-session"
      className="flex items-center gap-2 rounded-xl border bg-card py-2 pr-2 pl-4"
    >
      <Link
        href={`/speaking/${s.id}`}
        className="flex min-w-0 flex-1 flex-col gap-1 rounded-md py-1 outline-none focus-visible:outline-2 focus-visible:outline-ring"
      >
        <span className="truncate font-[550]">{title}</span>
        <span className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
          <time dateTime={s.started_at}>
            {format.dateTime(new Date(s.started_at), { dateStyle: "medium", timeStyle: "short" })}
          </time>
          <span aria-hidden>·</span>
          <span className="tabular-nums">{t("spoken", { minutes })}</span>
          {s.status === "active" && <Tag variant="brand">{t("status.active")}</Tag>}
          {s.status === "failed" && <Tag variant="warning">{t("status.failed")}</Tag>}
          {s.intelligibility && (
            <Tag variant={s.intelligibility === "hard" ? "warning" : "success"}>
              {t(`intelligibility.${s.intelligibility}`)}
            </Tag>
          )}
        </span>
      </Link>
      <InlineConfirm question={t("confirmDelete")} onConfirm={onDelete} compact>
        {(ask) => (
          <Button
            size="icon-xs"
            variant="ghost"
            aria-label={t("delete")}
            onClick={ask}
            className="shrink-0 text-muted-foreground hover:text-destructive"
          >
            <Trash2 />
          </Button>
        )}
      </InlineConfirm>
    </div>
  );
}
