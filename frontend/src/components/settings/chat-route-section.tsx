"use client";

import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api";
import type { Connection, Presets, TaskRoute } from "@/lib/types";

import { useDescribeError } from "./use-describe-error";

const MODEL_REF = /^[a-z0-9][a-z0-9_-]*:\S+$/; // "<connection>:<model>"

export function ChatRouteSection({
  presets,
  connections,
}: {
  presets: Presets;
  connections: Connection[];
}) {
  const t = useTranslations("settings.route");
  const describe = useDescribeError();
  const [route, setRoute] = useState<TaskRoute | null>(null);
  const [draft, setDraft] = useState<string | null>(null); // null = not editing
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);

  const load = () =>
    api<TaskRoute[]>("/tenant/routes").then(
      (all) => setRoute(all.find((r) => r.section === "llm" && r.task === "chat") ?? null),
      (e: unknown) => setMessage({ ok: false, text: describe(e) }),
    );
  // eslint-disable-next-line react-hooks/exhaustive-deps -- load once
  useEffect(() => void load(), []);

  // Models the tenant can route to: every connection x the models its preset lists.
  const suggestions = connections.flatMap((c) =>
    (presets.presets.find((p) => p.name === c.name)?.models ?? []).map((m) => `${c.name}:${m}`),
  );
  const models = (draft ?? "").split("\n").map((l) => l.trim()).filter(Boolean);
  const invalid = models.filter((m) => !MODEL_REF.test(m));

  async function save() {
    setMessage(null);
    try {
      setRoute(await api<TaskRoute>("/tenant/routes/llm/chat", { method: "PUT", json: { models } }));
      setDraft(null);
      setMessage({ ok: true, text: t("saved") });
    } catch (e) {
      setMessage({ ok: false, text: describe(e) });
    }
  }

  async function reset() {
    setMessage(null);
    try {
      await api("/tenant/routes/llm/chat", { method: "DELETE" });
      await load();
      setDraft(null);
      setMessage({ ok: true, text: t("resetDone") });
    } catch (e) {
      setMessage({ ok: false, text: describe(e) });
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("title")}</CardTitle>
        <CardDescription>{t("description")}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {route && draft === null && (
          <>
            <p className="text-xs text-muted-foreground">
              {route.overridden ? t("custom") : t("default")}
            </p>
            <ol className="list-decimal pl-5 font-mono text-sm" aria-label={t("title")}>
              {route.models.map((m) => (
                <li key={m}>
                  {m}
                  {!connections.some((c) => m.startsWith(`${c.name}:`)) && (
                    <span className="ml-2 font-sans text-xs text-muted-foreground">
                      {t("skipped")}
                    </span>
                  )}
                </li>
              ))}
            </ol>
            <div className="flex gap-2">
              <Button size="sm" variant="outline" onClick={() => setDraft(route.models.join("\n"))}>
                {t("edit")}
              </Button>
              {route.overridden && (
                <Button size="sm" variant="ghost" onClick={reset}>
                  {t("reset")}
                </Button>
              )}
            </div>
          </>
        )}
        {draft !== null && (
          <>
            <Textarea
              aria-label={t("editLabel")}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              rows={4}
              className="font-mono text-sm"
            />
            <p className="text-xs text-muted-foreground">{t("editHint")}</p>
            {suggestions.length > 0 && (
              <div className="flex flex-wrap gap-2">
                {suggestions.map((s) => (
                  <Button
                    key={s}
                    size="xs"
                    variant="secondary"
                    onClick={() => setDraft((d) => (d?.trim() ? `${d.trim()}\n${s}` : s))}
                  >
                    + {s}
                  </Button>
                ))}
              </div>
            )}
            {invalid.length > 0 && (
              <p role="alert" className="text-sm text-destructive">
                {t("invalid", { refs: invalid.join(", ") })}
              </p>
            )}
            <div className="flex gap-2">
              <Button size="sm" onClick={save} disabled={models.length === 0 || invalid.length > 0}>
                {t("save")}
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setDraft(null)}>
                {t("cancel")}
              </Button>
            </div>
          </>
        )}
        {message && (
          <p
            role="status"
            className={message.ok ? "text-sm text-emerald-600" : "text-sm text-destructive"}
          >
            {message.text}
          </p>
        )}
      </CardContent>
    </Card>
  );
}
