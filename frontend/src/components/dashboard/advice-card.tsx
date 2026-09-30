"use client";

import { RefreshCw } from "lucide-react";
import Link from "next/link";
import { useFormatter, useLocale, useTranslations } from "next-intl";
import { useCallback, useEffect, useRef, useState } from "react";

import { useDescribeError } from "@/components/settings/use-describe-error";
import { Button, buttonVariants } from "@/components/ui/button";
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  type Advice,
  type AdviceItem,
  adviceHref,
  fetchAdvice,
  POLL_MS,
  POLL_TIMES,
  refreshAdvice,
} from "@/lib/advice";
import { kcName, learnerHref } from "@/lib/learner";

const linkClass = "underline underline-offset-2";

/** Which template text an item gets: placement splits into first test, retest and resume. */
export function templateKey(item: AdviceItem) {
  if (item.kind !== "placement") return item.kind;
  if (item.in_progress) return "resume";
  return item.days_since === null ? "placement" : "retest";
}

function minutesUntil(iso: string | null): number | null {
  if (iso === null) return null;
  return Math.max(1, Math.ceil((Date.parse(iso) - Date.now()) / 60_000));
}

/**
 * Today's study advice (P1 plan §7.5.2): the learning engine proposes the actions, a model
 * picks up to three and writes why. Cached on the server and rewritten in the background,
 * so this shows what is there at once and asks again for a little while when new advice
 * is on its way. Items without model text use templates; the numbers are always live.
 */
export function AdviceCard() {
  const t = useTranslations("dashboard.advice");
  const format = useFormatter();
  const locale = useLocale();
  const describe = useDescribeError();
  const [advice, setAdvice] = useState<Advice | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Minutes until "refresh" is allowed again, as of the last response.
  const [waitMinutes, setWaitMinutes] = useState<number | null>(null);
  const polls = useRef(0);

  const load = useCallback(
    (request: Promise<Advice>) =>
      request.then(
        (a) => {
          setAdvice(a);
          setWaitMinutes(minutesUntil(a.refresh_after));
          setError(null);
        },
        (e: unknown) => setError(describe(e)),
      ),
    // eslint-disable-next-line react-hooks/exhaustive-deps -- describe is stable enough
    [],
  );

  useEffect(() => {
    polls.current = 0;
    void load(fetchAdvice(locale));
  }, [load, locale]);

  useEffect(() => {
    if (!advice?.refreshing || polls.current >= POLL_TIMES) return;
    const timer = setTimeout(() => {
      polls.current += 1;
      void load(fetchAdvice(locale));
    }, POLL_MS);
    return () => clearTimeout(timer);
  }, [advice, load, locale]);

  const refresh = () => {
    polls.current = 0;
    void load(refreshAdvice(locale));
  };

  return (
    <Card data-testid="advice">
      <CardHeader>
        <CardTitle>{t("title")}</CardTitle>
        <CardDescription data-testid="advice-status">
          {advice ? <Status advice={advice} /> : !error && t("loading")}
        </CardDescription>
        {advice && (
          <CardAction className="flex flex-col items-end gap-1">
            <Button
              size="sm"
              variant="outline"
              onClick={refresh}
              disabled={advice.refreshing || waitMinutes !== null}
            >
              <RefreshCw className={advice.refreshing ? "animate-spin" : undefined} />
              {t("refresh")}
            </Button>
            {waitMinutes !== null && (
              <span className="text-xs text-muted-foreground">
                {t("refreshAfter", { n: waitMinutes })}
              </span>
            )}
          </CardAction>
        )}
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}
        {advice && advice.items.length === 0 && (
          <p className="text-sm text-muted-foreground">
            {t.rich("empty", {
              chat: (text) => (
                <Link href="/chat" className={linkClass}>
                  {text}
                </Link>
              ),
            })}
          </p>
        )}
        {advice && advice.items.length > 0 && (
          <ol className="grid gap-3 md:grid-cols-3">
            {advice.items.map((item) => (
              <AdviceEntry key={item.candidate_id} item={item} />
            ))}
          </ol>
        )}
        {advice?.status === "ai" && advice.generated_at && (
          <p className="text-xs text-muted-foreground">
            {t("byAi", {
              time: format.dateTime(new Date(advice.generated_at), {
                dateStyle: "short",
                timeStyle: "short",
              }),
            })}
          </p>
        )}
      </CardContent>
    </Card>
  );
}

function Status({ advice }: { advice: Advice }) {
  const t = useTranslations("dashboard.advice");
  if (advice.refreshing && advice.status === null) return t("writing");
  if (advice.status === "no_model")
    return t.rich("noModel", {
      settings: (text) => (
        <Link href="/settings" className={linkClass}>
          {text}
        </Link>
      ),
    });
  if (advice.status === "failed") return t("failed");
  if (advice.refreshing) return t("writing");
  return t("rules");
}

function AdviceEntry({ item }: { item: AdviceItem }) {
  const t = useTranslations("dashboard.advice");
  const locale = useLocale();
  const key = templateKey(item);
  const kc = item.kc ? kcName(item.kc, locale) : "";
  const book = item.book ? (locale.startsWith("zh") ? item.book.name_zh : item.book.name_en) : "";
  return (
    <li
      className="flex flex-col gap-2 rounded-lg border p-3"
      data-testid="advice-item"
      data-kind={item.kind}
    >
      <div className="flex items-start gap-2">
        <span className="flex-1 font-medium">
          {item.title ?? t(`kinds.${key}.title`, { kc })}
        </span>
        {item.title && (
          <span className="rounded bg-muted px-1.5 py-0.5 text-xs text-muted-foreground">
            {t("aiBadge")}
          </span>
        )}
      </div>
      <p className="flex-1 text-sm text-muted-foreground">
        {item.reason ?? t(`kinds.${key}.reason`, { book })}
      </p>
      <Evidence item={item} kc={kc} />
      <div className="flex items-center gap-3">
        <Link href={adviceHref(item)} className={buttonVariants({ size: "sm" })}>
          {t(`kinds.${key}.action`)}
        </Link>
        {item.kind === "grammar_practice" && item.kc && (
          <Link href={learnerHref(item.kc.id)} className={linkClass}>
            {t("evidenceLink")}
          </Link>
        )}
      </div>
    </li>
  );
}

function Evidence({ item, kc }: { item: AdviceItem; kc: string }) {
  const t = useTranslations("dashboard.advice.evidence");
  const format = useFormatter();
  let text: string | null = null;
  switch (item.kind) {
    case "vocab_review":
      text = t("due", { n: item.count ?? 0 });
      break;
    case "vocab_learn":
      text = t("newLeft", { n: item.count ?? 0 });
      break;
    case "placement":
      if (item.in_progress) text = t("inProgress");
      else if (item.days_since !== null) text = t("lastTest", { n: item.days_since });
      break;
    case "grammar_practice":
      text = t("grammar", {
        kc,
        n: item.count ?? 0,
        p: format.number(item.p_mastery ?? 0, { style: "percent" }),
      });
      break;
  }
  return text ? (
    <p className="text-xs font-medium" data-testid="advice-evidence">
      {text}
    </p>
  ) : null;
}
