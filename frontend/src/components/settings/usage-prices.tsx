"use client";

import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { ErrorText } from "@/components/ui/error-text";
import { Input } from "@/components/ui/input";
import { Segmented } from "@/components/ui/segmented";
import { api } from "@/lib/api";
import { type ModelPrice, PRICE_CURRENCIES, type PriceCurrency, type Prices } from "@/lib/types";

import { useDescribeError } from "./use-describe-error";

const FIELDS = ["input_per_mtok", "output_per_mtok", "per_kchar", "per_minute"] as const;
type Field = (typeof FIELDS)[number];
type Draft = { connection: string; model: string } & Record<Field, string>;

function parsePrice(text: string): number | null | undefined {
  if (text.trim() === "") return null;
  const value = Number(text);
  return Number.isFinite(value) && value >= 0 && value <= 1_000_000 ? value : undefined;
}

/** The account's own prices per `connection:model` (ADR 0034 §3): none built in; only
 * models used in the shown range, plus ones already priced. Loaded when opened. */
export function UsagePrices({
  models,
  onSaved,
}: {
  models: { connection: string; model: string }[];
  onSaved: () => void;
}) {
  const t = useTranslations("settings.usage.prices");
  const describe = useDescribeError();
  const [open, setOpen] = useState(false);
  const [saved, setSaved] = useState<Prices | null>(null);
  const [currency, setCurrency] = useState<PriceCurrency>("CNY");
  const [drafts, setDrafts] = useState<Record<string, Draft>>({});
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open) return;
    let live = true;
    api<Prices>("/tenant/prices").then(
      (p) => {
        if (!live) return;
        setSaved(p);
        setCurrency(p.currency);
        setDrafts(Object.fromEntries(p.prices.map((price) => [keyOf(price), toDraft(price)])));
      },
      (e: unknown) => live && setError(describe(e)),
    );
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- describe changes with locale only
  }, [open]);

  const keys = [...new Set([...models.map(keyOf), ...(saved?.prices ?? []).map(keyOf)])].sort();
  const draftOf = (key: string): Draft => {
    const [connection, ...rest] = key.split(":");
    return drafts[key] ?? { connection, model: rest.join(":"), ...blank() };
  };
  const invalid = keys.some((k) => FIELDS.some((f) => parsePrice(draftOf(k)[f]) === undefined));

  async function save() {
    setSaving(true);
    try {
      const body: Prices = {
        currency,
        prices: keys.map((k) => {
          const d = draftOf(k);
          return {
            connection: d.connection,
            model: d.model,
            ...(Object.fromEntries(FIELDS.map((f) => [f, parsePrice(d[f]) ?? null])) as Record<Field, number | null>),
          };
        }),
      };
      const out = await api<Prices>("/tenant/prices", { method: "PUT", json: body });
      setSaved(out);
      setError(null);
      toast.success(t("saved"));
      onSaved();
    } catch (e) {
      setError(describe(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <details onToggle={(e) => setOpen(e.currentTarget.open)}>
      <summary className="cursor-pointer text-sm font-semibold">{t("title")}</summary>
      {open && (
        <div className="mt-2 flex flex-col gap-2">
          <p className="text-xs text-muted-foreground">{t("hint")}</p>
          {error && <ErrorText>{error}</ErrorText>}
          {saved && keys.length === 0 && <p className="text-sm text-muted-foreground">{t("noModels")}</p>}
          {saved && keys.length > 0 && (
            <>
              <div className="flex w-fit items-center gap-2 text-sm">
                {t("currency")}
                <Segmented
                  label={t("currency")}
                  size="sm"
                  value={currency}
                  onChange={setCurrency}
                  options={PRICE_CURRENCIES.map((c) => ({ value: c, label: c }))}
                />
              </div>
              <div className="overflow-x-auto rounded-lg border">
                <table className="w-full text-[13px] whitespace-nowrap" aria-label={t("title")}>
                  <thead className="bg-muted/60 text-left text-xs text-muted-foreground">
                    <tr>
                      <th className="px-3 py-2 font-medium">{t("model")}</th>
                      {FIELDS.map((f) => (
                        <th key={f} className="px-3 py-2 font-medium">
                          {t(f)}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {keys.map((k) => {
                      const d = draftOf(k);
                      return (
                        <tr key={k} className="border-t">
                          <td className="px-3 py-2 font-mono">{k}</td>
                          {FIELDS.map((f) => (
                            <td key={f} className="px-3 py-1.5">
                              <Input
                                aria-label={`${k} · ${t(f)}`}
                                type="number"
                                inputMode="decimal"
                                min={0}
                                step="any"
                                placeholder={t("none")}
                                value={d[f]}
                                aria-invalid={parsePrice(d[f]) === undefined}
                                onChange={(e) => setDrafts({ ...drafts, [k]: { ...d, [f]: e.target.value } })}
                                className="h-8 w-28"
                              />
                            </td>
                          ))}
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              <Button size="sm" className="w-fit" disabled={invalid || saving} onClick={() => void save()}>
                {t("save")}
              </Button>
            </>
          )}
        </div>
      )}
    </details>
  );
}

function keyOf(m: { connection: string; model: string }): string {
  return `${m.connection}:${m.model}`;
}

function blank(): Record<Field, string> {
  return { input_per_mtok: "", output_per_mtok: "", per_kchar: "", per_minute: "" };
}

function toDraft(price: ModelPrice): Draft {
  const text = (v: number | null) => (v === null ? "" : String(v));
  return {
    connection: price.connection,
    model: price.model,
    input_per_mtok: text(price.input_per_mtok),
    output_per_mtok: text(price.output_per_mtok),
    per_kchar: text(price.per_kchar),
    per_minute: text(price.per_minute),
  };
}
