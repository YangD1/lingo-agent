"use client";

import { useFormatter, useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import { useDescribeError } from "@/components/settings/use-describe-error";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ErrorText } from "@/components/ui/error-text";
import { api } from "@/lib/api";
import type { MyUsage } from "@/lib/types";
import { cn } from "@/lib/utils";

/**
 * The learner's own AI use this UTC month per capability, and, for a member, what's left
 * of the main account's quotas (ADR 0034 §4). No costs: those are for whoever pays.
 */
export function MyUsageCard() {
  const t = useTranslations("learner.usage");
  const tOrg = useTranslations("settings.org");
  const describe = useDescribeError();
  const format = useFormatter();
  const [usage, setUsage] = useState<MyUsage | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<MyUsage>("/me/usage").then(setUsage, (e: unknown) => setError(describe(e)));
    // eslint-disable-next-line react-hooks/exhaustive-deps -- describe changes with locale only
  }, []);

  const n = (v: number) => format.number(v, { maximumFractionDigits: 1 });
  // A capability shows once used, or when a quota for it was given.
  const shown = (usage?.capabilities ?? []).filter((c) => c.month > 0 || c.quota !== null);

  return (
    <Card data-testid="learner-usage">
      <CardHeader>
        <CardTitle>{t("title")}</CardTitle>
        <CardDescription>
          {usage?.sponsor_name ? t("sponsored", { name: usage.sponsor_name }) : t("description")}
        </CardDescription>
      </CardHeader>
      <CardContent>
        {error && <ErrorText>{error}</ErrorText>}
        {usage && shown.length === 0 && <p className="text-sm text-muted-foreground">{t("empty")}</p>}
        {shown.length > 0 && (
          <ul className="flex flex-col divide-y text-[13px]">
            {shown.map((c) => {
              const unit = tOrg(`units.${c.unit}`);
              const q = c.quota;
              return (
                <li key={c.capability} data-testid={`usage-${c.capability}`} className="flex min-h-11 items-center gap-3 py-2">
                  <span className="flex-1">{tOrg(`capabilities.${c.capability}`)}</span>
                  <span className="font-mono tabular-nums">{t("used", { amount: n(c.month), unit })}</span>
                  {q && (
                    <span
                      className={cn(
                        "w-28 shrink-0 text-right text-xs text-muted-foreground",
                        q.left !== null && q.left <= 0 && "text-destructive",
                      )}
                    >
                      {q.daily === 0 || q.monthly === 0
                        ? tOrg("off")
                        : q.left === null
                          ? tOrg("noCap")
                          : t("left", { amount: n(q.left), unit })}
                    </span>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
