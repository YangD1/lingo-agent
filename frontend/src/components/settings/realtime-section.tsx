"use client";

import { useFormatter, useTranslations } from "next-intl";
import { useCallback, useEffect, useState } from "react";

import { AiBadge } from "@/components/ai-badge";
import { Button } from "@/components/ui/button";
import { Callout } from "@/components/ui/callout";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ErrorText } from "@/components/ui/error-text";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError, api } from "@/lib/api";
import type { RealtimeLimits } from "@/lib/types";

import { useDescribeError } from "./use-describe-error";

// The backend's upper bounds (app/api/realtime.py).
const MAX_SESSION_MINUTES = 60;
const MAX_DAILY_MINUTES = 600;

/**
 * Realtime voice limits (ADR 0030 §5), for tenant owners/admins: one call's length and
 * each learner's minutes per UTC day; either at 0 turns calls off.
 */
export function RealtimeSection() {
  const t = useTranslations("settings.realtime");
  const describe = useDescribeError();
  // null: not loaded yet, or not a tenant manager (403): the card stays hidden.
  const [limits, setLimits] = useState<RealtimeLimits | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    api<RealtimeLimits>("/tenant/realtime").then(
      (l) => {
        setLimits(l);
        setError(null);
      },
      (e: unknown) => {
        if (!(e instanceof ApiError && e.status === 403)) setError(describe(e));
      },
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps -- describe changes with locale only
  }, []);
  useEffect(() => load(), [load]);

  if (!limits && !error) return null;

  return (
    <Card id="realtime" className="scroll-mt-14 lg:scroll-mt-4">
      <CardHeader>
        <CardTitle className="flex items-center gap-1.5">
          {t("title")}
          <AiBadge feature="realtime_call" />
        </CardTitle>
        <CardDescription>{t("description")}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {error && <ErrorText>{error}</ErrorText>}
        {limits && (
          // Keyed by what is stored: saving resets the drafts to it.
          <LimitsForm
            key={`${limits.session_minutes}/${limits.daily_minutes}`}
            limits={limits}
            onSaved={setLimits}
          />
        )}
      </CardContent>
    </Card>
  );
}

function LimitsForm({
  limits,
  onSaved,
}: {
  limits: RealtimeLimits;
  onSaved: (limits: RealtimeLimits) => void;
}) {
  const t = useTranslations("settings.realtime");
  const format = useFormatter();
  const describe = useDescribeError();
  const [session, setSession] = useState(String(limits.session_minutes));
  const [daily, setDaily] = useState(String(limits.daily_minutes));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const minutes = (draft: string, max: number) => {
    const value = Number(draft);
    return draft.trim() !== "" && Number.isInteger(value) && value >= 0 && value <= max ? value : null;
  };
  const sessionValue = minutes(session, MAX_SESSION_MINUTES);
  const dailyValue = minutes(daily, MAX_DAILY_MINUTES);
  const changed =
    sessionValue !== limits.session_minutes || dailyValue !== limits.daily_minutes;

  async function save() {
    if (sessionValue === null || dailyValue === null) return;
    setSaving(true);
    try {
      onSaved(
        await api<RealtimeLimits>("/tenant/realtime", {
          method: "PUT",
          json: { session_minutes: sessionValue, daily_minutes: dailyValue },
        }),
      );
      setError(null);
    } catch (e) {
      setError(describe(e));
      setSaving(false);
    }
  }

  return (
    <>
      {limits.state === "off" && <Callout tone="warning">{t("off")}</Callout>}
      <form
        className="flex flex-wrap items-end gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          void save();
        }}
      >
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="realtime-session-minutes">{t("sessionMinutes")}</Label>
          <Input
            id="realtime-session-minutes"
            type="number"
            inputMode="numeric"
            min={0}
            max={MAX_SESSION_MINUTES}
            value={session}
            aria-invalid={sessionValue === null}
            onChange={(e) => setSession(e.target.value)}
            className="w-28"
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="realtime-daily-minutes">{t("dailyMinutes")}</Label>
          <Input
            id="realtime-daily-minutes"
            type="number"
            inputMode="numeric"
            min={0}
            max={MAX_DAILY_MINUTES}
            value={daily}
            aria-invalid={dailyValue === null}
            onChange={(e) => setDaily(e.target.value)}
            className="w-28"
          />
        </div>
        <Button
          type="submit"
          disabled={sessionValue === null || dailyValue === null || !changed || saving}
        >
          {t("save")}
        </Button>
      </form>
      <p className="text-sm text-muted-foreground">{t("hint")}</p>
      {error && <ErrorText>{error}</ErrorText>}
      <p className="text-sm">
        {t("usedToday", {
          used: format.number(limits.used_minutes),
          limit: format.number(limits.daily_minutes),
        })}
      </p>
    </>
  );
}
