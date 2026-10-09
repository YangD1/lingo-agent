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
import { NativeSelect } from "@/components/ui/native-select";
import { ErrorText } from "@/components/ui/error-text";
import { api } from "@/lib/api";
import type { Usage, UsageRow } from "@/lib/types";
import { cn } from "@/lib/utils";
import { EmptyState } from "@/components/ui/empty-state";

import { useDescribeError } from "./use-describe-error";

const NUMERIC = ["calls", "input_tokens", "output_tokens", "characters", "errors", "fallbacks"] as const;

export function UsageSection() {
  const t = useTranslations("settings.usage");
  const format = useFormatter();
  const describe = useDescribeError();
  const [days, setDays] = useState(7);
  const [usage, setUsage] = useState<Usage | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(
    () =>
      api<Usage>(`/tenant/usage?days=${days}`).then(
        (u) => {
          setError(null);
          setUsage(u);
        },
        (e: unknown) => setError(describe(e)),
      ),
    // eslint-disable-next-line react-hooks/exhaustive-deps -- describe changes with locale only
    [days],
  );
  useEffect(() => void load(), [load]);

  const rows = usage?.rows ?? [];
  const total = (key: (typeof NUMERIC)[number]) => rows.reduce((sum, r) => sum + r[key], 0);
  // Read-aloud's column only once something was read aloud.
  const columns = NUMERIC.filter((key) => key !== "characters" || total("characters") > 0);
  const n = (value: number) => format.number(value);

  return (
    <Card id="usage" className="scroll-mt-14 lg:scroll-mt-4">
      <CardHeader>
        <CardTitle>{t("title")}</CardTitle>
        <CardDescription>{t("description")}</CardDescription>
        <CardAction className="flex items-center gap-1.5">
          <NativeSelect
            aria-label={t("range")}
            value={days}
            onChange={(e) => setDays(Number(e.target.value))}
            className="h-8 md:h-8"
          >
            {[7, 30, 90].map((d) => (
              <option key={d} value={d}>
                {t("lastDays", { days: d })}
              </option>
            ))}
          </NativeSelect>
          <Button size="icon-sm" variant="ghost" aria-label={t("refresh")} title={t("refresh")} onClick={load}>
            <RefreshCw />
          </Button>
        </CardAction>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {error &&
          (usage ? (
            <ErrorText>{error}</ErrorText>
          ) : (
            // Nothing loaded: the whole area failed, so the big oops cat.
            <EmptyState tone="error" title={error} />
          ))}
        {usage && rows.length === 0 && (
          <p className="rounded-lg border border-dashed px-4 py-6 text-center text-sm text-muted-foreground">
            {t("empty")}
          </p>
        )}
        {rows.length > 0 && (
          <div className="overflow-x-auto rounded-lg border">
            <table className="w-full text-[13px] whitespace-nowrap" aria-label={t("title")}>
              <thead className="bg-muted/60 text-left text-xs text-muted-foreground">
                <tr>
                  <th className="px-3 py-2 font-medium">{t("day")}</th>
                  <th className="px-3 py-2 font-medium">{t("model")}</th>
                  {columns.map((key) => (
                    <th key={key} className="px-3 py-2 text-right font-medium">
                      {t(key)}
                    </th>
                  ))}
                  <th className="px-3 py-2 text-right font-medium">{t("avg_latency_ms")}</th>
                </tr>
              </thead>
              <tbody className="font-mono">
                {rows.map((r: UsageRow) => (
                  <tr key={`${r.day}/${r.connection}/${r.model}`} className="border-t">
                    <td className="px-3 py-2">{r.day}</td>
                    <td className="px-3 py-2">{`${r.connection}:${r.model}`}</td>
                    {columns.map((key) => (
                      <td
                        key={key}
                        className={cn(
                          "px-3 py-2 text-right",
                          key === "errors" && r.errors > 0 && "text-destructive",
                        )}
                      >
                        {n(r[key])}
                      </td>
                    ))}
                    <td className="px-3 py-2 text-right">{n(r.avg_latency_ms)}</td>
                  </tr>
                ))}
              </tbody>
              <tfoot className="font-mono font-semibold">
                <tr className="border-t bg-muted/30">
                  <td className="px-3 py-2 font-sans" colSpan={2}>
                    {t("total")}
                  </td>
                  {columns.map((key) => (
                    <td key={key} className="px-3 py-2 text-right">
                      {n(total(key))}
                    </td>
                  ))}
                  <td />
                </tr>
              </tfoot>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
