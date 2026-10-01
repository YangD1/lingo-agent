"use client";

import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import { AiBadge } from "@/components/ai-badge";
import { type EmptyActions, TutorPanel } from "@/components/chat/tutor-panel";
import { AdviceEntry, useAdvice } from "@/components/dashboard/advice-entry";
import { Button, buttonVariants } from "@/components/ui/button";
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import type { ApiErrorLike } from "@/i18n/errors";
import type { Advice } from "@/lib/advice";
import { ApiError, api } from "@/lib/api";
import type { Conversation } from "@/lib/types";

const linkClass = "underline underline-offset-2";

const startPlanning = (locale: string) =>
  api<Conversation>("/conversations", { method: "POST", json: { purpose: "planning", locale } });

/** The latest planning conversation started since the test finished, if any (ADR 0016 §4). */
export async function findPlanning(finishedAt: string | null): Promise<Conversation | null> {
  if (!finishedAt) return null;
  const since = new Date(finishedAt).getTime();
  const all = await api<Conversation[]>("/conversations");
  return (
    all
      .filter((c) => c.purpose === "planning" && new Date(c.created_at).getTime() >= since)
      .sort((a, b) => b.created_at.localeCompare(a.created_at))[0] ?? null
  );
}

/**
 * What to do next, on the placement result: the planning conversation for this test,
 * in the page (ADR 0016 §4, Q23f). Nothing calls a model until the learner asks the
 * tutor to go through the result, or types a message (which skips the opening).
 */
export function PlacementTutor({ finishedAt }: { finishedAt: string | null }) {
  const t = useTranslations("placement.result");
  const locale = useLocale();
  const { advice, error: adviceError } = useAdvice();
  // undefined: still looking for this test's planning conversation.
  const [conversation, setConversation] = useState<Conversation | null | undefined>(undefined);
  // The learner pressed the button: the tutor opens once the conversation is ready.
  const [opening, setOpening] = useState(false);
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState<ApiErrorLike | null>(null);
  useEffect(() => {
    findPlanning(finishedAt).then(setConversation, () => setConversation(null));
  }, [finishedAt]);

  async function talk(actions: EmptyActions) {
    if (conversation) return actions.open();
    setStarting(true);
    setStartError(null);
    try {
      setConversation(await startPlanning(locale));
      setOpening(true);
    } catch (e) {
      setStartError(e instanceof ApiError ? e : { code: "network_error", message: "" });
    } finally {
      setStarting(false);
    }
  }

  return (
    <Card data-testid="placement-next">
      <CardHeader>
        <CardTitle>{t("nextTitle")}</CardTitle>
        <CardDescription>{t("nextDescription")}</CardDescription>
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
          <p className="text-sm text-muted-foreground">{t("nextLoading")}</p>
        ) : (
          <TutorPanel
            className="h-[32rem] rounded-lg border bg-muted/50"
            conversationId={conversation?.id ?? null}
            onConversationCreated={setConversation}
            createConversation={() => startPlanning(locale)}
            // The backend may hand back an existing empty planning conversation.
            discardRefused={false}
            autoOpen={opening}
            error={startError}
            empty={(actions) => (
              <PlanStart
                advice={advice}
                error={adviceError}
                busy={actions.busy || starting}
                onTalk={() => void talk(actions)}
              />
            )}
          />
        )}
      </CardContent>
    </Card>
  );
}

/** Before the conversation starts: the way in, or the rule advice without a model. */
export function PlanStart({
  advice,
  error,
  busy,
  onTalk,
}: {
  advice: Advice | null;
  error: string | null;
  busy: boolean;
  onTalk: () => void;
}) {
  const t = useTranslations("placement.result");
  const tAdvice = useTranslations("dashboard.advice");

  if (error)
    return (
      <p role="alert" className="flex-1 p-4 text-sm text-destructive">
        {error}
      </p>
    );
  if (!advice) return <p className="flex-1 p-4 text-sm text-muted-foreground">{t("nextLoading")}</p>;

  if (!advice.model_ready)
    return (
      <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-4" data-testid="plan-rules">
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

  return (
    <div className="flex min-h-0 flex-1 flex-col items-center justify-center gap-3 overflow-y-auto p-4 text-center">
      <p className="max-w-prose text-sm text-muted-foreground">{t("planNote")}</p>
      <div className="flex flex-wrap items-center justify-center gap-2">
        <Button disabled={busy} onClick={onTalk} data-testid="placement-plan">
          {t("plan")}
        </Button>
        <AiBadge feature="plan_start" />
      </div>
      <p className="text-xs text-muted-foreground">{t("planTyping")}</p>
    </div>
  );
}
