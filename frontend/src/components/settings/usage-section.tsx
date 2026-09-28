"use client";

import { useFormatter, useTranslations } from "next-intl";
import { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { NativeSelect } from "@/components/ui/native-select";
import { api } from "@/lib/api";
import type { Usage, UsageRow } from "@/lib/types";

import { useDescribeError } from "./use-describe-error";

const NUMERIC = ["calls", "input_tokens", "output_tokens", "errors", "fallbacks"] as const;

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
  const n = (value: number) => format.number(value);

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("title")}</CardTitle>
        <CardDescription>{t("description")}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <div className="flex items-center gap-2">
          <NativeSelect
            aria-label={t("range")}
            value={days}
            onChange={(e) => setDays(Number(e.target.value))}
          >
            {[7, 30, 90].map((d) => (
              <option key={d} value={d}>
                {t("lastDays", { days: d })}
              </option>
            ))}
          </NativeSelect>
          <Button size="sm" variant="ghost" onClick={load}>
            {t("refresh")}
          </Button>
        </div>
        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}
        {usage && rows.length === 0 && (
          <p className="text-sm text-muted-foreground">{t("empty")}</p>
        )}
        {rows.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-sm" aria-label={t("title")}>
              <thead className="text-left text-xs text-muted-foreground">
                <tr>
                  <th className="py-2 pr-4 font-medium">{t("day")}</th>
                  <th className="py-2 pr-4 font-medium">{t("model")}</th>
                  {NUMERIC.map((key) => (
                    <th key={key} className="py-2 pr-4 text-right font-medium">
                      {t(key)}
                    </th>
                  ))}
                  <th className="py-2 text-right font-medium">{t("avg_latency_ms")}</th>
                </tr>
              </thead>
              <tbody className="tabular-nums">
                {rows.map((r: UsageRow) => (
                  <tr key={`${r.day}/${r.connection}/${r.model}`} className="border-t">
                    <td className="py-2 pr-4">{r.day}</td>
                    <td className="py-2 pr-4 font-mono">{`${r.connection}:${r.model}`}</td>
                    {NUMERIC.map((key) => (
                      <td key={key} className="py-2 pr-4 text-right">
                        {n(r[key])}
                      </td>
                    ))}
                    <td className="py-2 text-right">{n(r.avg_latency_ms)}</td>
                  </tr>
                ))}
              </tbody>
              <tfoot className="tabular-nums font-medium">
                <tr className="border-t">
                  <td className="py-2 pr-4" colSpan={2}>
                    {t("total")}
                  </td>
                  {NUMERIC.map((key) => (
                    <td key={key} className="py-2 pr-4 text-right">
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
