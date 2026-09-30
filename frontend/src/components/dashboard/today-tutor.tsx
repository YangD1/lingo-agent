"use client";

import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import { AiBadge } from "@/components/ai-badge";
import { type EmptyActions, TutorPanel } from "@/components/chat/tutor-panel";
import { Button, buttonVariants } from "@/components/ui/button";
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { type Advice, type AdviceItem, templateKey } from "@/lib/advice";
import { api } from "@/lib/api";
import { kcName } from "@/lib/learner";
import type { Conversation } from "@/lib/types";
import { browserTimeZone } from "@/lib/vocab";

import { AdviceEntry, useAdvice } from "./advice-entry";

const linkClass = "underline underline-offset-2";

/** Quick replies from the top candidates, after the fixed "what should I study today?". */
const QUICK_FROM = 3;

function timeZoneQuery(): string {
  const tz = browserTimeZone();
  return tz ? `?${new URLSearchParams({ tz })}` : "";
}

export const fetchToday = () => api<Conversation | null>(`/conversations/today${timeZoneQuery()}`);

/**
 * Today's conversation with the tutor on the dashboard (ADR 0016 §1–3). Before the first
 * message it shows a greeting and quick replies made by rules, and calls no model; the
 * conversation is created with the learner's first message, one per day.
 */
export function TodayTutor({ onTurnFinished }: { onTurnFinished?: () => void }) {
  const t = useTranslations("dashboard.today");
  const locale = useLocale();
  const { advice, error } = useAdvice();
  // undefined: still asking whether today's conversation exists.
  const [conversation, setConversation] = useState<Conversation | null | undefined>(undefined);
  useEffect(() => {
    fetchToday().then(setConversation, () => setConversation(null));
  }, []);

  return (
    <Card data-testid="today">
      <CardHeader>
        <CardTitle>{t("title")}</CardTitle>
        <CardDescription>{t("description")}</CardDescription>
        {conversation && (
          <CardAction>
            <Link
              href={`/chat?c=${conversation.id}`}
              className={buttonVariants({ size: "sm", variant: "outline" })}
            >
              {t("continueInChat")}
            </Link>
          </CardAction>
        )}
      </CardHeader>
      <CardContent>
        {conversation === undefined ? (
          <p className="text-sm text-muted-foreground">{t("loading")}</p>
        ) : (
          <TutorPanel
            className="h-[32rem] rounded-lg border"
            conversationId={conversation?.id ?? null}
            onConversationCreated={setConversation}
            onTurnFinished={onTurnFinished}
            createConversation={() =>
              api<Conversation>("/conversations", {
                method: "POST",
                json: { purpose: "daily", locale, tz: browserTimeZone() },
              })
            }
            discardRefused={false}
            empty={(actions) => <TodayStart advice={advice} error={error} actions={actions} />}
          />
        )}
      </CardContent>
    </Card>
  );
}

/** Before today's first message: a greeting and quick replies, or links without a model. */
export function TodayStart({
  advice,
  error,
  actions,
}: {
  advice: Advice | null;
  error: string | null;
  actions: EmptyActions;
}) {
  const t = useTranslations("dashboard.today");
  const tAdvice = useTranslations("dashboard.advice");
  const quick = useQuickReply();

  if (error)
    return (
      <p role="alert" className="flex-1 p-4 text-sm text-destructive">
        {error}
      </p>
    );
  if (!advice) return <p className="flex-1 p-4 text-sm text-muted-foreground">{t("loading")}</p>;

  if (!advice.model_ready)
    return (
      <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-4" data-testid="today-rules">
        <p className="text-sm text-muted-foreground">
          {tAdvice.rich("noModel", {
            settings: (text) => (
              <Link href="/settings" className={linkClass}>
                {text}
              </Link>
            ),
          })}
        </p>
        {advice.items.length > 0 && (
          <ol className="grid gap-3 md:grid-cols-3">
            {advice.items.map((item) => (
              <AdviceEntry key={item.candidate_id} item={item} />
            ))}
          </ol>
        )}
      </div>
    );

  const replies = [t("quick.whatToday"), ...advice.items.slice(0, QUICK_FROM).map(quick)];
  return (
    <div className="flex min-h-0 flex-1 flex-col justify-end gap-3 overflow-y-auto p-4">
      <p className="max-w-[85%] self-start rounded-lg bg-muted px-4 py-2" data-testid="today-greeting">
        <Greeting item={advice.items[0]} />
      </p>
      <div className="flex flex-wrap items-center justify-end gap-2" data-testid="today-quick">
        {replies.map((text, i) => (
          <Button
            key={i}
            size="sm"
            variant="outline"
            disabled={actions.busy}
            onClick={() => void actions.send(text)}
          >
            {text}
          </Button>
        ))}
        <AiBadge feature="chat_message" />
      </div>
    </div>
  );
}

function Greeting({ item }: { item: AdviceItem | undefined }) {
  const t = useTranslations("dashboard.today.greeting");
  const locale = useLocale();
  if (!item) return t("none");
  return t(templateKey(item), {
    n: item.count ?? 0,
    kc: item.kc ? kcName(item.kc, locale) : "",
    days: item.days_since ?? 0,
  });
}

/** What the learner says by picking a candidate, in the UI language (ADR 0016 §2). */
function useQuickReply() {
  const t = useTranslations("dashboard.today.quick");
  const locale = useLocale();
  return (item: AdviceItem) =>
    t(templateKey(item), {
      n: item.count ?? 0,
      kc: item.kc ? kcName(item.kc, locale) : "",
      book: item.book ? (locale.startsWith("zh") ? item.book.name_zh : item.book.name_en) : "",
    });
}
