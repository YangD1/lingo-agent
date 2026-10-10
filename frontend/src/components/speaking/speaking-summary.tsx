"use client";

import { ArrowLeftIcon, CheckIcon, PlusIcon, RotateCcwIcon } from "lucide-react";
import { useFormatter, useLocale, useTranslations } from "next-intl";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { type ReactNode, useState } from "react";

import { AiBadge } from "@/components/ai-badge";
import { LingoCat } from "@/components/brand/lingo-cat";
import { useDescribeError } from "@/components/settings/use-describe-error";
import { ShadowingBadge, ShadowingButton } from "@/components/speech/shadowing-button";
import { ShadowingPanel } from "@/components/speech/shadowing-panel";
import { Button, buttonVariants } from "@/components/ui/button";
import { ErrorText } from "@/components/ui/error-text";
import { Tag } from "@/components/ui/tag";
import { ApiError } from "@/lib/api";
import {
  endSession,
  type Scenario,
  scenarioTitle,
  type SpeakingSessionDetail,
  type SpeakingSummary,
  startSession,
} from "@/lib/speaking";
import { addMine } from "@/lib/vocab";

/**
 * A speaking practice once it has ended (task 59.5, ADR 0029 §5): what went well, the
 * mistakes in the learner's own words with the fix, more natural ways to say things, and
 * expressions to try next time, each one to shadow or put on the word list. A summary
 * that failed can be made again.
 */
export function SpeakingSummaryView({
  detail,
  scenario,
  onChange,
}: {
  detail: SpeakingSessionDetail;
  scenario: Scenario | null;
  onChange: (detail: SpeakingSessionDetail) => void;
}) {
  const t = useTranslations("speaking.summary");
  const locale = useLocale();
  const format = useFormatter();
  const router = useRouter();
  const describe = useDescribeError();
  const [busy, setBusy] = useState<"retry" | "again" | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function retry() {
    setBusy("retry");
    setError(null);
    try {
      onChange(await endSession(detail.id));
    } catch (e) {
      setError(describe(e));
    } finally {
      setBusy(null);
    }
  }

  async function again() {
    setBusy("again");
    setError(null);
    try {
      const next = await startSession(detail.scenario_id, locale);
      router.push(`/speaking/${next.id}`);
    } catch (e) {
      setError(describe(e));
      setBusy(null);
    }
  }

  const title = scenario ? scenarioTitle(scenario, locale) : t("freeTalk");
  const minutes = Math.round(detail.spoken_seconds / 6) / 10;
  const summary = detail.summary;

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="mx-auto flex max-w-2xl flex-col gap-4 p-4 md:px-10 md:py-8" data-testid="speaking-summary" data-status={detail.status}>
        <header className="flex flex-col gap-2">
          <div className="flex items-center gap-2">
            <Link
              href="/speaking"
              aria-label={t("back")}
              className={buttonVariants({ size: "icon-sm", variant: "ghost" })}
            >
              <ArrowLeftIcon />
            </Link>
            <h1 className="min-w-0 flex-1 truncate text-xl font-semibold">{title}</h1>
            <Button size="sm" variant="outline" disabled={busy !== null} onClick={() => void again()}>
              <RotateCcwIcon />
              {t("again")}
            </Button>
          </div>
          <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-muted-foreground">
            <time dateTime={detail.started_at}>
              {format.dateTime(new Date(detail.started_at), { dateStyle: "medium", timeStyle: "short" })}
            </time>
            <span aria-hidden>·</span>
            <span className="tabular-nums">{t("turns", { n: detail.turns })}</span>
            <span aria-hidden>·</span>
            <span className="tabular-nums">{t("spoken", { minutes })}</span>
            {summary && (
              <Tag variant={summary.intelligibility === "hard" ? "warning" : "success"} data-testid="speaking-intelligibility">
                {t(`intelligibility.${summary.intelligibility}`)}
              </Tag>
            )}
          </p>
        </header>

        {error && <ErrorText>{error}</ErrorText>}

        {detail.status === "failed" && (
          <div className="flex flex-col items-center gap-3 rounded-xl border border-dashed px-6 py-8 text-center text-sm text-muted-foreground">
            <LingoCat mood="oops" size={48} label="" />
            {t("failed")}
            <Button size="sm" disabled={busy !== null} onClick={() => void retry()}>
              {busy === "retry" ? t("retrying") : t("retry")}
              <AiBadge feature="speaking_summary" />
            </Button>
          </div>
        )}
        {detail.status === "done" && !summary && (
          <div className="flex flex-col items-center gap-3 rounded-xl border border-dashed px-6 py-8 text-center text-sm text-muted-foreground">
            <LingoCat mood="idle" size={48} label="" />
            {t("nothingSaid")}
          </div>
        )}
        {summary && <SummaryBody summary={summary} sessionId={detail.id} />}
      </div>
    </div>
  );
}

function SummaryBody({ summary: s, sessionId }: { summary: SpeakingSummary; sessionId: string }) {
  const t = useTranslations("speaking.summary");
  // One sentence is shadowed at a time.
  const [shadowing, setShadowing] = useState<string | null>(null);
  const shadow = (key: string, sentence: string) => (
    <Shadow
      open={shadowing === key}
      onToggle={() => setShadowing((now) => (now === key ? null : key))}
      sentence={sentence}
    />
  );

  return (
    <div className="flex flex-col gap-5">
      <p className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
        {t("aiNote")}
        <AiBadge feature="speaking_summary" />
        <ShadowingBadge />
      </p>
      {s.went_well.length > 0 && (
        <Section title={t("wentWell")} testId="summary-went-well">
          {s.went_well.map((text) => (
            <li key={text} className="flex gap-2">
              <CheckIcon aria-hidden className="mt-1 size-4 shrink-0 text-success" />
              <span>{text}</span>
            </li>
          ))}
        </Section>
      )}
      {s.mistakes.length > 0 && (
        <Section title={t("mistakes")} testId="summary-mistakes">
          {s.mistakes.map((m, i) => (
            <li key={`${m.quote}-${i}`} className="flex flex-col gap-1 rounded-lg border bg-card px-3.5 py-3">
              <span lang="en" className="text-muted-foreground line-through">
                {m.quote}
              </span>
              <span lang="en" className="font-[550]">
                {m.correction}
                {shadow(`mistake-${i}`, m.correction)}
              </span>
              <span className="text-sm text-muted-foreground">{m.explanation}</span>
              {shadowing === `mistake-${i}` && (
                <ShadowingPanel
                  sentences={[m.correction]}
                  source="speaking"
                  sourceId={sessionId}
                  onClose={() => setShadowing(null)}
                  className="mt-1"
                />
              )}
            </li>
          ))}
        </Section>
      )}
      {s.more_natural.length > 0 && (
        <Section title={t("moreNatural")} testId="summary-more-natural">
          {s.more_natural.map((n, i) => (
            <li key={`${n.quote}-${i}`} className="flex flex-col gap-1 rounded-lg border bg-card px-3.5 py-3">
              <span lang="en" className="text-muted-foreground">
                {t("youSaid", { quote: n.quote })}
              </span>
              <span lang="en" className="font-[550]">
                {n.natural}
                {shadow(`natural-${i}`, n.natural)}
              </span>
              <span className="text-sm text-muted-foreground">{n.note}</span>
              {shadowing === `natural-${i}` && (
                <ShadowingPanel
                  sentences={[n.natural]}
                  source="speaking"
                  sourceId={sessionId}
                  onClose={() => setShadowing(null)}
                  className="mt-1"
                />
              )}
            </li>
          ))}
        </Section>
      )}
      {s.next_expressions.length > 0 && (
        <Section title={t("nextTime")} testId="summary-next">
          {s.next_expressions.map((e, i) => (
            <li key={`${e.expression}-${i}`} className="flex flex-col gap-1 rounded-lg border bg-card px-3.5 py-3">
              <span className="flex flex-wrap items-center gap-1.5">
                <span lang="en" className="font-[550]">
                  {e.expression}
                </span>
                {shadow(`next-${i}`, e.expression)}
                <AddExpression expression={e.expression} />
              </span>
              <span className="text-sm text-muted-foreground">{e.meaning}</span>
              {shadowing === `next-${i}` && (
                <ShadowingPanel
                  sentences={[e.expression]}
                  source="speaking"
                  sourceId={sessionId}
                  onClose={() => setShadowing(null)}
                  className="mt-1"
                />
              )}
            </li>
          ))}
        </Section>
      )}
    </div>
  );
}

function Section({ title, testId, children }: { title: string; testId: string; children: ReactNode }) {
  return (
    <section aria-label={title} data-testid={testId} className="flex flex-col gap-2">
      <h2 className="text-sm font-semibold">{title}</h2>
      <ul className="flex flex-col gap-2">{children}</ul>
    </section>
  );
}

function Shadow({
  open,
  onToggle,
  sentence,
}: {
  open: boolean;
  onToggle: () => void;
  sentence: string;
}) {
  const t = useTranslations("speaking.summary");
  return <ShadowingButton compact open={open} onToggle={onToggle} label={t("shadow", { sentence })} className="ml-1" />;
}

/** Puts an expression on the word list, when the dictionary has it. */
function AddExpression({ expression }: { expression: string }) {
  const t = useTranslations("speaking.summary");
  const describe = useDescribeError();
  const [state, setState] = useState<"idle" | "busy" | "added" | "missing" | "failed">("idle");
  const [error, setError] = useState<string | null>(null);
  if (state === "added") return <Tag variant="success">{t("added")}</Tag>;
  if (state === "missing") return <span className="text-xs text-muted-foreground">{t("notInDictionary")}</span>;
  return (
    <>
      <Button
        size="xs"
        variant="ghost"
        disabled={state === "busy"}
        onClick={async () => {
          setState("busy");
          try {
            await addMine(expression);
            setState("added");
          } catch (e) {
            const missing = e instanceof ApiError && e.code === "word_not_found";
            setState(missing ? "missing" : "failed");
            if (!missing) setError(describe(e));
          }
        }}
      >
        <PlusIcon />
        {t("addToList")}
      </Button>
      {state === "failed" && error && <ErrorText size="xs">{error}</ErrorText>}
    </>
  );
}
