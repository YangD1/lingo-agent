"use client";

import { RefreshCw } from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";
import { useCallback, useEffect, useState } from "react";

import { AiBadge } from "@/components/ai-badge";
import { Button } from "@/components/ui/button";
import { Callout } from "@/components/ui/callout";
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { ErrorText } from "@/components/ui/error-text";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { ApiError, api } from "@/lib/api";
import type { MyBackground, SchedulerJob, TenantBackground } from "@/lib/types";

import { useDescribeError } from "./use-describe-error";

/**
 * Work the tutor does while nobody waits (ADR 0025): the learner's switches for each
 * kind, and for tenant owners/admins the daily token budget and how scheduled jobs went.
 */
export function BackgroundSection() {
  const t = useTranslations("settings.background");
  const describe = useDescribeError();
  const [mine, setMine] = useState<MyBackground | null>(null);
  // null: not loaded yet or not a tenant manager (403); the budget part stays hidden.
  const [tenant, setTenant] = useState<TenantBackground | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(() => {
    api<MyBackground>("/me/background").then(
      (m) => {
        setError(null);
        setMine(m);
      },
      (e: unknown) => setError(describe(e)),
    );
    api<TenantBackground>("/tenant/background").then(setTenant, (e: unknown) => {
      if (!(e instanceof ApiError && e.status === 403)) setError(describe(e));
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- describe changes with locale only
  }, []);
  useEffect(() => load(), [load]);

  async function toggle(key: string, enabled: boolean) {
    setBusy(key);
    try {
      setMine(
        await api<MyBackground>(`/me/background/${key}`, {
          method: "PUT",
          json: { enabled },
        }),
      );
      setError(null);
    } catch (e) {
      setError(describe(e));
    } finally {
      setBusy(null);
    }
  }

  return (
    <Card id="background" className="scroll-mt-14 lg:scroll-mt-4">
      <CardHeader>
        <CardTitle>{t("title")}</CardTitle>
        <CardDescription>{t("description")}</CardDescription>
        <CardAction>
          <Button size="icon-sm" variant="ghost" aria-label={t("refresh")} title={t("refresh")} onClick={load}>
            <RefreshCw />
          </Button>
        </CardAction>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {error && <ErrorText>{error}</ErrorText>}
        {mine && mine.budget !== "ok" && (
          <Callout tone="warning">{t(mine.budget === "off" ? "budgetOff" : "budgetExhausted")}</Callout>
        )}
        {mine && (
          <ul className="flex flex-col gap-3">
            {mine.features.map((f) => (
              <li key={f.key} className="flex items-start gap-3">
                <Switch
                  className="mt-0.5"
                  aria-label={featureName(t, f.key)}
                  checked={f.enabled}
                  disabled={busy === f.key}
                  onCheckedChange={(on) => void toggle(f.key, on)}
                />
                <div className="min-w-0 flex-1 text-sm">
                  <p className="flex items-center gap-1.5 font-medium">
                    {featureName(t, f.key)}
                    <AiBadge feature={f.usage_feature} />
                  </p>
                  {optional(t, `features.${f.key}.hint`) && (
                    <p className="text-muted-foreground">{optional(t, `features.${f.key}.hint`)}</p>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
        {tenant && (
          // Keyed by the saved limit: saving resets the draft to what was stored.
          <TenantBudget key={tenant.daily_tokens} tenant={tenant} onChange={setTenant} onSaved={load} />
        )}
      </CardContent>
    </Card>
  );
}

type Translate = ReturnType<typeof useTranslations<"settings.background">>;

/** The message at a key built from server data, or undefined when there is none. */
function optional(t: Translate, path: string): string | undefined {
  const key = path as Parameters<Translate>[0];
  return t.has(key) ? t(key) : undefined;
}

function featureName(t: Translate, key: string): string {
  return optional(t, `features.${key}.name`) ?? key;
}

function TenantBudget({
  tenant,
  onChange,
  onSaved,
}: {
  tenant: TenantBackground;
  onChange: (tenant: TenantBackground) => void;
  onSaved: () => void;
}) {
  const t = useTranslations("settings.background");
  const format = useFormatter();
  const describe = useDescribeError();
  const [draft, setDraft] = useState(String(tenant.daily_tokens));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const value = Number(draft);
  const valid = draft.trim() !== "" && Number.isInteger(value) && value >= 0 && value <= 100_000_000;

  async function save() {
    setSaving(true);
    try {
      onChange(
        await api<TenantBackground>("/tenant/background", {
          method: "PUT",
          json: { daily_tokens: value },
        }),
      );
      setError(null);
      onSaved(); // the learner side's budget state may have changed too
    } catch (e) {
      setError(describe(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <section aria-labelledby="background-budget" className="flex flex-col gap-3 border-t pt-4">
      <h3 id="background-budget" className="text-sm font-semibold">
        {t("budgetTitle")}
      </h3>
      <p className="text-sm text-muted-foreground">{t("budgetHint")}</p>
      <form
        className="flex flex-wrap items-end gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (valid) void save();
        }}
      >
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="background-daily-tokens">{t("dailyTokens")}</Label>
          <Input
            id="background-daily-tokens"
            type="number"
            inputMode="numeric"
            min={0}
            max={100_000_000}
            step={1000}
            value={draft}
            aria-invalid={!valid}
            onChange={(e) => setDraft(e.target.value)}
            className="w-40"
          />
        </div>
        <Button type="submit" disabled={!valid || saving || value === tenant.daily_tokens}>
          {t("save")}
        </Button>
      </form>
      {error && <ErrorText>{error}</ErrorText>}
      <p className="text-sm">
        {t("usedToday", {
          used: format.number(tenant.used_today),
          limit: format.number(tenant.daily_tokens),
        })}
      </p>
      <h3 className="text-sm font-semibold">{t("jobsTitle")}</h3>
      {!tenant.scheduler_running && <p className="text-sm text-muted-foreground">{t("schedulerOff")}</p>}
      {tenant.jobs.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t("noJobs")}</p>
      ) : (
        <ul className="flex flex-col gap-2 text-sm">
          {tenant.jobs.map((job) => (
            <JobRow key={job.job} job={job} />
          ))}
        </ul>
      )}
    </section>
  );
}

function JobRow({ job }: { job: SchedulerJob }) {
  const t = useTranslations("settings.background");
  const format = useFormatter();
  const when = (iso: string | null) =>
    iso ? format.dateTime(new Date(iso), { dateStyle: "short", timeStyle: "short" }) : t("never");
  const name = optional(t, `jobs.${job.job}`) ?? job.job;
  return (
    <li className="flex flex-col gap-0.5">
      <span className="font-medium">{name}</span>
      <span className="text-muted-foreground">
        {t("jobLast", {
          status: t(`status.${job.last_status ?? "never"}`),
          when: when(job.last_finished_at ?? job.last_started_at),
        })}
        {job.next_run_at && ` · ${t("jobNext", { when: when(job.next_run_at) })}`}
      </span>
      {job.last_status === "skipped" && job.last_skip_reason && (
        <span className="text-muted-foreground">
          {optional(t, `skip.${job.last_skip_reason}`) ?? job.last_skip_reason}
        </span>
      )}
      {job.last_status === "error" && job.last_error && <ErrorText>{job.last_error}</ErrorText>}
    </li>
  );
}
