"use client";

import { useFormatter, useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import { ErrorText } from "@/components/ui/error-text";
import { NativeSelect } from "@/components/ui/native-select";
import { api } from "@/lib/api";
import type { Usage, UsageRow } from "@/lib/types";
import { cn } from "@/lib/utils";

import { useDescribeError } from "./use-describe-error";

const NUMERIC = ["calls", "input_tokens", "output_tokens", "characters", "errors", "fallbacks"] as const;

/** Per day and model, one account at a time (`GET /tenant/usage`, ADR 0005). Loaded when
 * shown; `reload` bumps with the dashboard's refresh. */
export function UsageDetails({ days, reload }: { days: number; reload: number }) {
  const t = useTranslations("settings.usage");
  const format = useFormatter();
  const describe = useDescribeError();
  const [usage, setUsage] = useState<Usage | null>(null);
  // null: this account's own calls; else a member's (ADR 0031 §8).
  const [whose, setWhose] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    api<Usage>(`/tenant/usage?days=${days}`).then(
      (u) => {
        if (!live) return;
        setError(null);
        setUsage(u);
      },
      (e: unknown) => live && setError(describe(e)),
    );
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- describe changes with locale only
  }, [days, reload]);

  const members = [...new Set((usage?.rows ?? []).flatMap((r) => (r.member === null ? [] : [r.member])))];
  // A member gone from the range shows the account's own calls again.
  const shownWhose = whose !== null && members.includes(whose) ? whose : null;
  const rows = (usage?.rows ?? []).filter((r) => r.member === shownWhose);
  const total = (key: (typeof NUMERIC)[number]) => rows.reduce((sum, r) => sum + r[key], 0);
  // Read-aloud's column only once something was read aloud.
  const columns = NUMERIC.filter((key) => key !== "characters" || total("characters") > 0);
  const n = (value: number) => format.number(value);

  return (
    <div className="flex flex-col gap-2">
      {error && <ErrorText>{error}</ErrorText>}
      {members.length > 0 && (
        <NativeSelect
          aria-label={t("whose")}
          value={shownWhose ?? ""}
          onChange={(e) => setWhose(e.target.value || null)}
          className="h-8 w-fit md:h-8"
        >
          <option value="">{t("mine")}</option>
          {members.map((m) => (
            <option key={m} value={m}>
              {m}
            </option>
          ))}
        </NativeSelect>
      )}
      {usage && rows.length === 0 && <p className="text-sm text-muted-foreground">{t("empty")}</p>}
      {rows.length > 0 && (
        <div className="overflow-x-auto rounded-lg border">
          <table className="w-full text-[13px] whitespace-nowrap" aria-label={t("details")}>
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
                      className={cn("px-3 py-2 text-right", key === "errors" && r.errors > 0 && "text-destructive")}
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
    </div>
  );
}
