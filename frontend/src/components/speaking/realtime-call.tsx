"use client";

import {
  ArrowLeftIcon,
  EyeIcon,
  EyeOffIcon,
  HeadphonesIcon,
  MicIcon,
  MicOffIcon,
  PhoneIcon,
  PhoneOffIcon,
} from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { AiBadge } from "@/components/ai-badge";
import { CatLoading, LingoCat } from "@/components/brand/lingo-cat";
import { Button, buttonVariants } from "@/components/ui/button";
import { Callout } from "@/components/ui/callout";
import { Tag } from "@/components/ui/tag";
import type { Activity, CollectedWord, WordsCollected } from "@/lib/activity";
import { useSpeakingHideText } from "@/lib/preferences";
import { type CallLine, type CallState, remainingSeconds, type SubtitleLine } from "@/lib/realtime-call";
import { fetchScenarios, type Scenario, scenarioGoal, scenarioTitle } from "@/lib/speaking";
import { refreshCapabilities } from "@/lib/speech";
import { cn } from "@/lib/utils";
import { removeMine } from "@/lib/vocab";

import { useRealtimeCall } from "./use-realtime-call";

// Refusals that a setting fixes: the page links there.
const SETTINGS_CODES = new Set(["no_realtime_model", "realtime_off"]);
// Refusals with their own text; others fall back to a general one.
const REFUSALS = new Set([
  "no_realtime_model",
  "realtime_off",
  "realtime_used_up",
  "realtime_busy",
  "realtime_unavailable",
  "unknown_scenario",
]);

/** m:ss */
export const clock = (seconds: number) =>
  `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;

/**
 * A realtime call with the tutor (task 62, ADR 0030, Q62a–h): connect, talk with live
 * subtitles and what the tutor did, see the time left, hang up. Once a call has been
 * taken it goes on to its detail page (transcript and summary); a call that never
 * began stays here with why.
 */
export function RealtimeCallPage({ scenarioId }: { scenarioId: string | null }) {
  const t = useTranslations("speaking.call");
  const locale = useLocale();
  const router = useRouter();
  const call = useRealtimeCall();
  const { state } = call;
  const [scenario, setScenario] = useState<Scenario | null>(null);
  const [hideText, setHideText] = useSpeakingHideText();

  useEffect(() => {
    if (!scenarioId) return;
    fetchScenarios().then(
      (all) => setScenario(all.scenarios.find((s) => s.id === scenarioId) ?? null),
      () => {}, // only the title and goal: the call itself checks the scenario
    );
  }, [scenarioId]);

  const inCall = state.phase === "connecting" || state.phase === "live" || state.phase === "wrapping";
  // Closing or reloading the tab mid-call asks first (Q62g).
  useEffect(() => {
    if (!inCall) return;
    const guard = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", guard);
    return () => window.removeEventListener("beforeunload", guard);
  }, [inCall]);

  // A call that was taken goes on to its transcript and summary (Q62b); the minutes
  // left today changed.
  const sessionId = state.session_id;
  const endReason = state.phase === "ended" ? state.end_reason : null;
  useEffect(() => {
    if (!sessionId || !endReason) return;
    void refreshCapabilities();
    router.replace(`/speaking/${sessionId}?call_end=${endReason}`);
  }, [sessionId, endReason, router]);

  const title = scenario ? scenarioTitle(scenario, locale) : scenarioId ? "" : t("freeTalk");
  const goal = scenario ? scenarioGoal(scenario, locale) : scenarioId ? "" : t("freeTalkGoal");
  const live = state.phase === "live" || state.phase === "wrapping";

  return (
    <section className="flex min-h-0 min-w-0 flex-1 flex-col" data-testid="realtime-call" data-phase={state.phase}>
      <header className="mx-auto flex w-full max-w-3xl flex-col gap-2 border-b px-3 py-3 md:px-8">
        <div className="flex items-center gap-2">
          {!inCall && (
            <Link
              href="/speaking"
              aria-label={t("back")}
              className={buttonVariants({ size: "icon-sm", variant: "ghost" })}
            >
              <ArrowLeftIcon />
            </Link>
          )}
          <h1 className="min-w-0 flex-1 truncate text-base font-semibold">{title}</h1>
          {live && (
            <span
              role="timer"
              aria-label={t("timeLeft")}
              data-testid="call-time-left"
              className={cn(
                "font-mono text-sm tabular-nums",
                state.warned ? "font-semibold text-destructive" : "text-muted-foreground",
              )}
            >
              {clock(remainingSeconds(state))}
            </span>
          )}
          <Button
            size="icon-sm"
            variant="ghost"
            aria-pressed={hideText}
            aria-label={t("hideText")}
            title={t("hideText")}
            onClick={() => setHideText(!hideText)}
          >
            {hideText ? <EyeOffIcon /> : <EyeIcon />}
          </Button>
        </div>
        {goal && <p className="text-sm text-muted-foreground">{goal}</p>}
        {scenario && scenario.target_expressions.length > 0 && (
          <p className="flex flex-wrap items-center gap-1 text-xs text-muted-foreground">
            {t("tryUsing")}
            <span lang="en" className="flex flex-wrap gap-1">
              {scenario.target_expressions.map((e) => (
                <Tag key={e}>{e}</Tag>
              ))}
            </span>
          </p>
        )}
      </header>

      {state.phase === "idle" && <BeforeCall onConnect={() => void call.start(scenarioId)} />}
      {state.phase === "connecting" && (
        <div className="m-auto flex flex-col items-center gap-4">
          <CatLoading size={48} label={t("connecting")} />
          <Button variant="outline" onClick={call.hangUp}>
            {t("cancel")}
          </Button>
        </div>
      )}
      {live && <Subtitles lines={state.lines} hideTutor={hideText} />}
      {state.phase === "ended" && !state.session_id && (
        <NotConnected state={state} onRetry={() => void call.start(scenarioId)} />
      )}
      {state.phase === "ended" && state.session_id && (
        <CatLoading size={48} className="m-auto" label={t("ended")} />
      )}

      {live && (
        <footer className="mx-auto flex w-full max-w-3xl flex-col gap-2 border-t px-3 py-3 md:px-8">
          {state.phase === "wrapping" ? (
            <p role="status" className="text-center text-sm text-muted-foreground">
              {t("wrappingUp")}
            </p>
          ) : (
            state.warned && (
              <p role="status" className="text-center text-sm text-destructive">
                {t("warning")}
              </p>
            )
          )}
          {state.end_suggested && (
            <div
              role="alert"
              data-testid="call-end-suggested"
              className="flex items-center gap-2 rounded-lg border bg-muted/50 px-3 py-2 text-sm"
            >
              <span className="flex-1">{t("endSuggested")}</span>
              <Button size="sm" variant="ghost" onClick={call.dismissEnd}>
                {t("keepTalking")}
              </Button>
              <Button size="sm" variant="destructive" onClick={call.hangUp}>
                {t("hangUp")}
              </Button>
            </div>
          )}
          <div className="flex items-center justify-center gap-4">
            <Button
              size="icon-lg"
              variant="outline"
              aria-pressed={call.muted}
              aria-label={call.muted ? t("unmute") : t("mute")}
              title={call.muted ? t("unmute") : t("mute")}
              disabled={state.phase === "wrapping"}
              onClick={() => call.setMuted(!call.muted)}
            >
              {call.muted ? <MicOffIcon /> : <MicIcon />}
            </Button>
            <Level value={call.level} />
            <Button
              size="icon-lg"
              variant="destructive"
              className="size-14 rounded-full"
              aria-label={t("hangUp")}
              title={t("hangUp")}
              onClick={call.hangUp}
              data-testid="call-hang-up"
            >
              <PhoneOffIcon />
            </Button>
          </div>
        </footer>
      )}
    </section>
  );
}

function BeforeCall({ onConnect }: { onConnect: () => void }) {
  const t = useTranslations("speaking.call");
  return (
    <div className="m-auto flex max-w-sm flex-col items-center gap-4 px-4 text-center">
      <div className="relative">
        <Button
          size="icon-lg"
          className="size-20 rounded-full"
          aria-label={t("connect")}
          onClick={onConnect}
          data-testid="call-connect"
        >
          <PhoneIcon className="size-8" />
        </Button>
        <AiBadge feature="realtime_call" corner />
      </div>
      <p className="font-medium">{t("connect")}</p>
      <p className="flex items-center gap-1.5 text-sm text-muted-foreground">
        <HeadphonesIcon className="size-4 shrink-0" />
        {t("headphones")}
      </p>
      <p className="text-xs text-muted-foreground">{t("howItWorks")}</p>
    </div>
  );
}

/** The microphone's loudness: a short bar beside the mute button. */
function Level({ value }: { value: number }) {
  return (
    <div className="h-2 w-16 overflow-hidden rounded-full bg-muted" aria-hidden>
      <div className="h-full bg-primary transition-[width]" style={{ width: `${Math.round(value * 100)}%` }} />
    </div>
  );
}

function Subtitles({ lines, hideTutor }: { lines: CallLine[]; hideTutor: boolean }) {
  const t = useTranslations("speaking.call");
  const end = useRef<HTMLLIElement>(null);
  useEffect(() => {
    end.current?.scrollIntoView?.({ block: "end" });
  }, [lines]);
  return (
    <ol className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-2 overflow-y-auto px-3 py-4 md:px-8" aria-live="polite">
      {lines.length === 0 && <CatLoading size={40} className="m-auto" label={t("opening")} />}
      {lines.map((line, i) =>
        line.kind === "subtitle" ? (
          <SubtitleBubble key={`${line.role}-${line.item_id ?? `held-${i}`}`} line={line} hidden={hideTutor && line.role === "tutor"} />
        ) : (
          line.activity.name !== "end_session" && <ToolChip key={line.activity.call_id} activity={line.activity} />
        ),
      )}
      <li ref={end} aria-hidden />
    </ol>
  );
}

function SubtitleBubble({ line, hidden }: { line: SubtitleLine; hidden: boolean }) {
  const t = useTranslations("speaking.call");
  const learner = line.role === "learner";
  return (
    <li
      data-role={learner ? "user" : "assistant"}
      data-final={line.final}
      className={cn(
        "max-w-[85%] rounded-2xl px-3.5 py-2 text-sm",
        learner ? "self-end bg-brand-soft text-brand-soft-foreground" : "self-start bg-muted",
        !line.final && "opacity-70",
      )}
      lang="en"
    >
      {hidden ? (
        <span className="text-muted-foreground" lang={undefined}>
          {t("hiddenText")}
        </span>
      ) : line.text ? (
        line.text
      ) : (
        <span aria-label={t("listening")}>…</span>
      )}
    </li>
  );
}

/** What the tutor did, in the flow of the talk (Q62e); a word just added can be taken off. */
function ToolChip({ activity }: { activity: Activity }) {
  const t = useTranslations("speaking.call.tool");
  const [undone, setUndone] = useState<"busy" | "done" | "failed" | null>(null);
  let text: string;
  let added: CollectedWord | null = null;
  if (activity.status !== "ok") {
    text = activity.name === "lookup_word" ? t("lookupFailed") : t("addFailed");
  } else if (activity.name === "lookup_word") {
    const { word, word_id } = activity.summary as { word: string; word_id?: number | null };
    text = word_id ? t("lookedUp", { word }) : t("notFound", { word });
  } else if (activity.name === "add_to_vocab") {
    const summary = activity.summary as WordsCollected;
    added = summary.added?.[0] ?? null;
    const existing = summary.existing?.[0];
    text = added
      ? t("added", { word: added.word })
      : existing
        ? t("existing", { word: existing.word })
        : t("addNotFound");
  } else {
    return null;
  }

  async function undo(word: CollectedWord) {
    setUndone("busy");
    try {
      await removeMine(word.word_id);
      setUndone("done");
    } catch {
      setUndone("failed");
    }
  }

  return (
    <li className="flex items-center justify-center gap-1.5 text-xs text-muted-foreground" data-testid="call-tool" data-tool={activity.name}>
      <LingoCat mood={activity.status === "ok" ? "done" : "oops"} size={14} label="" />
      <span>{undone === "done" ? t("undone") : text}</span>
      {added && undone !== "done" && (
        <Button size="xs" variant="ghost" disabled={undone === "busy"} onClick={() => void undo(added)}>
          {undone === "failed" ? t("undoFailed") : t("undo")}
        </Button>
      )}
    </li>
  );
}

/** A call that never began: why, and what to do about it. */
function NotConnected({ state, onRetry }: { state: CallState; onRetry: () => void }) {
  const t = useTranslations("speaking.call");
  const code = state.refused_code;
  const message =
    state.end_reason === "refused"
      ? code === "rate_limited"
        ? t("refused.rate_limited", { seconds: state.retry_after ?? 1 })
        : code && REFUSALS.has(code)
        ? t(`refused.${code}` as Parameters<typeof t>[0])
        : t("refused.other")
      : t(`endReason.${state.end_reason ?? "error"}` as Parameters<typeof t>[0]);
  const retry = code !== "realtime_used_up" && code !== "realtime_off" && code !== "unknown_scenario";
  return (
    <div className="m-auto flex max-w-sm flex-col items-center gap-3 px-4 text-center" data-testid="call-not-connected">
      <LingoCat mood="oops" size={48} label="" />
      <div role="alert">
        <Callout tone="warning">{message}</Callout>
      </div>
      <div className="flex gap-2">
        {code && SETTINGS_CODES.has(code) ? (
          <Link href="/settings" className={buttonVariants({ variant: "outline" })}>
            {t("goToSettings")}
          </Link>
        ) : (
          <Link href="/speaking" className={buttonVariants({ variant: "outline" })}>
            {t("back")}
          </Link>
        )}
        {retry && <Button onClick={onRetry}>{t("retry")}</Button>}
      </div>
    </div>
  );
}
