"use client";

import { useTranslations } from "next-intl";
import { useCallback, useEffect, useState } from "react";

import { AiBadge } from "@/components/ai-badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ErrorText } from "@/components/ui/error-text";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { ApiError, api } from "@/lib/api";
import type { DeepenSettings } from "@/lib/types";

import { useDescribeError } from "./use-describe-error";

type Limit = Exclude<keyof DeepenSettings, "enabled">;

// The backend's bounds (app/chat/deepen.py), in the order the form shows them.
export const DEEPEN_BOUNDS: readonly (readonly [Limit, number, number])[] = [
  ["max_segments", 1, 3],
  ["first_chunk_seconds", 5, 60],
  ["total_seconds", 10, 300],
  ["max_tokens", 256, 8000],
];

/**
 * Limits on the tutor's follow-up segments (ADR 0064 §5), for tenant owners/admins:
 * whether the tutor may add one, how many per reply, how long one may wait and run,
 * and how long it may be.
 */
export function DeepenSection() {
  const t = useTranslations("settings.deepen");
  const describe = useDescribeError();
  // null: not loaded yet, or not a tenant manager (403): the card stays hidden.
  const [stored, setStored] = useState<DeepenSettings | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    api<DeepenSettings>("/tenant/deepen").then(
      (s) => {
        setStored(s);
        setError(null);
      },
      (e: unknown) => {
        if (!(e instanceof ApiError && e.status === 403)) setError(describe(e));
      },
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps -- describe changes with locale only
  }, []);
  useEffect(() => load(), [load]);

  if (!stored && !error) return null;

  return (
    <Card id="deepen" className="scroll-mt-14 lg:scroll-mt-4">
      <CardHeader>
        <CardTitle className="flex items-center gap-1.5">
          {t("title")}
          <AiBadge feature="chat_message" />
        </CardTitle>
        <CardDescription>{t("description")}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {error && <ErrorText>{error}</ErrorText>}
        {stored && (
          // Keyed by what is stored: saving resets the drafts to it.
          <DeepenForm key={JSON.stringify(stored)} stored={stored} onSaved={setStored} />
        )}
      </CardContent>
    </Card>
  );
}

function DeepenForm({
  stored,
  onSaved,
}: {
  stored: DeepenSettings;
  onSaved: (settings: DeepenSettings) => void;
}) {
  const t = useTranslations("settings.deepen");
  const describe = useDescribeError();
  const [enabled, setEnabled] = useState(stored.enabled);
  const [drafts, setDrafts] = useState<Record<Limit, string>>(
    () => Object.fromEntries(DEEPEN_BOUNDS.map(([key]) => [key, String(stored[key])])) as Record<Limit, string>,
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const values = Object.fromEntries(
    DEEPEN_BOUNDS.map(([key, min, max]) => {
      const draft = drafts[key];
      const value = Number(draft);
      const ok = draft.trim() !== "" && Number.isInteger(value) && value >= min && value <= max;
      return [key, ok ? value : null];
    }),
  ) as Record<Limit, number | null>;
  const valid = DEEPEN_BOUNDS.every(([key]) => values[key] !== null);
  const changed =
    enabled !== stored.enabled || DEEPEN_BOUNDS.some(([key]) => values[key] !== stored[key]);

  async function save() {
    if (!valid) return;
    setSaving(true);
    try {
      onSaved(
        await api<DeepenSettings>("/tenant/deepen", {
          method: "PUT",
          json: { enabled, ...(values as Record<Limit, number>) },
        }),
      );
      setError(null);
    } catch (e) {
      setError(describe(e));
      setSaving(false);
    }
  }

  return (
    <form
      className="flex flex-col gap-4"
      onSubmit={(e) => {
        e.preventDefault();
        void save();
      }}
    >
      <div className="flex items-start gap-3">
        <Switch
          id="deepen-enabled"
          className="mt-0.5"
          checked={enabled}
          onCheckedChange={setEnabled}
        />
        <div className="min-w-0 flex-1 text-sm">
          <Label htmlFor="deepen-enabled">{t("enabled")}</Label>
          <p className="text-muted-foreground">{t("enabledHint")}</p>
        </div>
      </div>
      <div className="flex flex-wrap items-end gap-2">
        {DEEPEN_BOUNDS.map(([key, min, max]) => (
          <div key={key} className="flex flex-col gap-1.5">
            <Label htmlFor={`deepen-${key}`}>{t(`fields.${key}`)}</Label>
            <Input
              id={`deepen-${key}`}
              type="number"
              inputMode="numeric"
              min={min}
              max={max}
              value={drafts[key]}
              disabled={!enabled}
              aria-invalid={values[key] === null}
              onChange={(e) => setDrafts((d) => ({ ...d, [key]: e.target.value }))}
              className="w-32"
            />
          </div>
        ))}
        <Button type="submit" disabled={!valid || !changed || saving}>
          {t("save")}
        </Button>
      </div>
      <p className="text-sm text-muted-foreground">{t("hint")}</p>
      {error && <ErrorText>{error}</ErrorText>}
    </form>
  );
}
