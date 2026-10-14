"use client";

import { RefreshCw } from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";
import { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorText } from "@/components/ui/error-text";
import { Select } from "@/components/ui/select";
import { Segmented } from "@/components/ui/segmented";
import { Tag } from "@/components/ui/tag";
import { isAiTask, loadEstimates } from "@/lib/ai-usage";
import { api } from "@/lib/api";
import type { UsageDashboard, UsageTally } from "@/lib/types";
import { cn } from "@/lib/utils";

import { type ChartMetric, UsageChart } from "./usage-chart";
import { UsageDetails } from "./usage-details";
import { UsagePrices } from "./usage-prices";
import { useDescribeError } from "./use-describe-error";

type Grouping = "tasks" | "models" | "members";
type GroupRow = { key: string; name: string; hint?: string; background?: boolean; tally: UsageTally };

/** Where this account's model calls went and, with prices entered, what they cost (ADR 0034). */
export function UsageSection() {
  const t = useTranslations("settings.usage");
  const tTask = useTranslations("aiBadge.task");
  const format = useFormatter();
  const describe = useDescribeError();
  const [days, setDays] = useState(7);
  const [board, setBoard] = useState<UsageDashboard | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [metric, setMetric] = useState<ChartMetric>("calls");
  const [grouping, setGrouping] = useState<Grouping>("tasks");
  const [details, setDetails] = useState(false);
  const [reload, setReload] = useState(0);
  // task -> the features that make it (features.yaml), for the hover hint.
  const [featuresOf, setFeaturesOf] = useState<Record<string, string[]>>({});

  const load = useCallback(
    () =>
      api<UsageDashboard>(`/tenant/usage/dashboard?days=${days}`).then(
        (b) => {
          setError(null);
          setBoard(b);
        },
        (e: unknown) => setError(describe(e)),
      ),
    // eslint-disable-next-line react-hooks/exhaustive-deps -- describe changes with locale only
    [days],
  );
  useEffect(() => void load(), [load]);
  useEffect(() => {
    loadEstimates().then(
      (estimates) => {
        const out: Record<string, string[]> = {};
        for (const f of estimates.features)
          for (const c of f.calls) if (!(out[c.task] ??= []).includes(f.feature)) out[c.task].push(f.feature);
        setFeaturesOf(out);
      },
      // Only the hint is missing.
      () => undefined,
    );
  }, []);

  const n = (v: number) => format.number(v);
  const minutes = (v: number) => format.number(v, { maximumFractionDigits: 1 });
  const percent = (part: number, whole: number) =>
    format.number(whole ? part / whole : 0, { style: "percent", maximumFractionDigits: 1 });
  const money = (v: number) =>
    format.number(v, { style: "currency", currency: board?.currency ?? "CNY", maximumFractionDigits: 2 });
  const cost = (tally: UsageTally) =>
    tally.cost === null ? "—" : `${money(tally.cost)}${tally.cost_partial ? "*" : ""}`;

  const total = board?.total;
  const shownMetric = metric === "cost" && !board?.priced ? "calls" : metric;
  // Members only once someone else used this account's connections (ADR 0031 §8).
  const hasMembers = (board?.members ?? []).some((m) => m.member !== null);
  const shownGrouping = grouping === "members" && !hasMembers ? "tasks" : grouping;
  // Keys built from server data: anything added later just shows its id.
  const named = (prefix: "feature" | "task", id: string) => {
    const key = `${prefix}.${id}` as Parameters<typeof t>[0];
    return t.has(key) ? t(key) : id;
  };
  const featureName = (feature: string) => named("feature", feature);
  // Tasks no feature makes (connection tests) are named here, not in the AI badge.
  const taskName = (task: string) => (isAiTask(task) ? tTask(task) : named("task", task));
  const rows: GroupRow[] = !board
    ? []
    : shownGrouping === "tasks"
      ? board.tasks.map((r) => ({
          key: `${r.task}/${r.background}`,
          name: taskName(r.task),
          hint: featuresOf[r.task]?.length
            ? t("usedBy", { features: featuresOf[r.task].map(featureName).join(t("separator")) })
            : r.task,
          background: r.background,
          tally: r,
        }))
      : shownGrouping === "models"
        ? board.models.map((r) => ({ key: `${r.connection}:${r.model}`, name: `${r.connection}:${r.model}`, tally: r }))
        : board.members.map((r) => ({ key: r.member ?? "", name: r.member ?? t("mine"), tally: r }));

  return (
    <Card id="usage" className="scroll-mt-14 lg:scroll-mt-4">
      <CardHeader>
        <CardTitle>{t("title")}</CardTitle>
        <CardDescription>{t("description")}</CardDescription>
        <CardAction className="flex items-center gap-1.5">
          <Select
            aria-label={t("range")}
            value={days}
            onValueChange={setDays}
            size="sm"
            className="w-auto"
            options={[7, 30, 90].map((d) => ({ value: d, label: t("lastDays", { days: d }) }))}
          />
          <Button
            size="icon-sm"
            variant="ghost"
            aria-label={t("refresh")}
            title={t("refresh")}
            onClick={() => {
              void load();
              setReload((r) => r + 1);
            }}
          >
            <RefreshCw />
          </Button>
        </CardAction>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {error &&
          (board ? (
            <ErrorText>{error}</ErrorText>
          ) : (
            // Nothing loaded: the whole area failed, so the big oops cat.
            <EmptyState tone="error" title={error} />
          ))}
        {board && total && total.calls === 0 && (
          <p className="rounded-lg border border-dashed px-4 py-6 text-center text-sm text-muted-foreground">
            {t("empty")}
          </p>
        )}
        {board && total && total.calls > 0 && (
          <>
            <dl className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4" aria-label={t("totals")}>
              <Stat label={t("calls")} value={n(total.calls)} />
              <Stat
                label={t("tokens")}
                value={format.number(total.input_tokens + total.output_tokens, { notation: "compact" })}
                sub={t("tokensSplit", { input: n(total.input_tokens), output: n(total.output_tokens) })}
              />
              {total.characters > 0 && <Stat label={t("characters")} value={n(total.characters)} />}
              {total.audio_minutes > 0 && <Stat label={t("audio_minutes")} value={minutes(total.audio_minutes)} />}
              <Stat
                label={t("errorRate")}
                value={percent(total.errors, total.calls)}
                tone={total.errors > 0 ? "bad" : undefined}
              />
              <Stat label={t("fallbackRate")} value={percent(total.fallbacks, total.calls)} />
              {board.priced && total.cost !== null && (
                <Stat
                  label={t("cost")}
                  value={money(total.cost)}
                  sub={total.cost_partial ? t("costPartial") : t("costNote")}
                />
              )}
            </dl>

            <div className="flex flex-col gap-2">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h3 className="text-sm font-semibold">{t("perDay")}</h3>
                <Segmented
                  size="sm"
                  label={t("metricLabel")}
                  value={shownMetric}
                  onChange={setMetric}
                  options={[
                    { value: "calls", label: t("metric.calls") },
                    { value: "tokens", label: t("metric.tokens") },
                    ...(board.priced ? [{ value: "cost" as const, label: t("metric.cost") }] : []),
                  ]}
                />
              </div>
              <UsageChart board={board} metric={shownMetric} />
            </div>

            <div className="flex flex-col gap-2">
              <Segmented
                size="sm"
                label={t("groupLabel")}
                value={shownGrouping}
                onChange={setGrouping}
                className="w-fit"
                options={[
                  { value: "tasks", label: t("group.tasks") },
                  { value: "models", label: t("group.models") },
                  ...(hasMembers ? [{ value: "members" as const, label: t("group.members") }] : []),
                ]}
              />
              <div className="overflow-x-auto rounded-lg border">
                <table className="w-full text-[13px] whitespace-nowrap" aria-label={t(`group.${shownGrouping}`)}>
                  <thead className="bg-muted/60 text-left text-xs text-muted-foreground">
                    <tr>
                      <th className="px-3 py-2 font-medium">{t(`groupColumn.${shownGrouping}`)}</th>
                      <th className="px-3 py-2 text-right font-medium">{t("calls")}</th>
                      <th className="px-3 py-2 text-right font-medium">{t("tokens")}</th>
                      {total.characters > 0 && <th className="px-3 py-2 text-right font-medium">{t("characters")}</th>}
                      {total.audio_minutes > 0 && (
                        <th className="px-3 py-2 text-right font-medium">{t("audio_minutes")}</th>
                      )}
                      <th className="px-3 py-2 text-right font-medium">{t("errors")}</th>
                      {board.priced && <th className="px-3 py-2 text-right font-medium">{t("cost")}</th>}
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((r) => (
                      <tr key={r.key} className="border-t">
                        <td className="px-3 py-2" title={r.hint}>
                          {r.name}
                          {r.background && <Tag className="ml-1.5">{t("background")}</Tag>}
                        </td>
                        <td className="px-3 py-2 text-right font-mono">{n(r.tally.calls)}</td>
                        <td className="px-3 py-2 text-right font-mono">
                          {n(r.tally.input_tokens + r.tally.output_tokens)}
                        </td>
                        {total.characters > 0 && (
                          <td className="px-3 py-2 text-right font-mono">{n(r.tally.characters)}</td>
                        )}
                        {total.audio_minutes > 0 && (
                          <td className="px-3 py-2 text-right font-mono">{minutes(r.tally.audio_minutes)}</td>
                        )}
                        <td
                          className={cn("px-3 py-2 text-right font-mono", r.tally.errors > 0 && "text-destructive")}
                        >
                          {n(r.tally.errors)}
                        </td>
                        {board.priced && <td className="px-3 py-2 text-right font-mono">{cost(r.tally)}</td>}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {board.priced && <p className="text-xs text-muted-foreground">{t("costFootnote")}</p>}
            </div>

            <details className="group" onToggle={(e) => setDetails(e.currentTarget.open)}>
              <summary className="cursor-pointer text-sm font-semibold">{t("details")}</summary>
              <div className="mt-2">{details && <UsageDetails days={days} reload={reload} />}</div>
            </details>
          </>
        )}
        {board && (
          <UsagePrices
            models={board.models.map((m) => ({ connection: m.connection, model: m.model }))}
            onSaved={() => void load()}
          />
        )}
      </CardContent>
    </Card>
  );
}

function Stat({ label, value, sub, tone }: { label: string; value: string; sub?: string; tone?: "bad" }) {
  return (
    <div className="rounded-lg border px-3 py-2">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className={cn("font-mono text-lg font-semibold tabular-nums", tone === "bad" && "text-destructive")}>
        {value}
      </dd>
      {sub && <dd className="text-xs text-muted-foreground">{sub}</dd>}
    </div>
  );
}
