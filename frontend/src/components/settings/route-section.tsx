"use client";

import { ArrowDown, ArrowUp, Plus, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useRef, useState } from "react";

import { AutocompleteInput } from "@/components/ui/autocomplete";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { NativeSelect } from "@/components/ui/native-select";
import { Tag } from "@/components/ui/tag";
import { ErrorText } from "@/components/ui/error-text";
import { api } from "@/lib/api";
import type { Connection, TaskRoute } from "@/lib/types";
import { cn } from "@/lib/utils";

import { fetchModels } from "./model-catalog";
import { useDescribeError } from "./use-describe-error";

const MAX_ROWS = 5; // the backend's limit on a route's fallback chain

/**
 * The routes the settings page edits: chat, the two that attachments need (ADR 0008 §5),
 * and the background model that keeps the tutor's memory (ADR 0009).
 */
export type RouteTask = "chat" | "reflect" | "vision" | "asr";
const SECTION: Record<RouteTask, TaskRoute["section"]> = {
  chat: "llm",
  reflect: "llm",
  vision: "llm",
  asr: "asr",
};
// The asr section has a single route, stored under the task name "default".
const TASK_KEY: Record<RouteTask, string> = {
  chat: "chat",
  reflect: "reflect",
  vision: "vision",
  asr: "default",
};
// A connection's default model is a chat model: only a good first guess for these.
const TEXT_TASKS = new Set<RouteTask>(["chat", "reflect"]);

type Row = { key: number; connection: string; model: string };
// Per connection name: its chat models, or why they aren't there (the user can still type one).
type Catalogs = Record<string, string[] | "loading" | "failed">;

export function RouteSection({
  task,
  connections,
  compact = false,
}: {
  task: RouteTask;
  connections: Connection[];
  /** A smaller card, for the routes shown side by side. */
  compact?: boolean;
}) {
  const t = useTranslations("settings.route");
  const section = SECTION[task];
  const path = `/tenant/routes/${section}/${TASK_KEY[task]}`;
  const describe = useDescribeError();
  const [route, setRoute] = useState<TaskRoute | null>(null);
  const [rows, setRows] = useState<Row[] | null>(null); // null = not editing
  const [catalogs, setCatalogs] = useState<Catalogs>({});
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const nextKey = useRef(0);

  const load = () =>
    api<TaskRoute[]>("/tenant/routes").then(
      (all) =>
        setRoute(all.find((r) => r.section === section && r.task === TASK_KEY[task]) ?? null),
      (e: unknown) => setMessage({ ok: false, text: describe(e) }),
    );
  // What runs depends on the connections (and their default models): reload when they change.
  // eslint-disable-next-line react-hooks/exhaustive-deps -- load is stable in effect
  useEffect(() => void load(), [connections]);

  const row = (connection: string, model: string): Row => ({
    key: nextKey.current++,
    connection,
    model,
  });

  function startEditing() {
    if (!route) return;
    setMessage(null);
    // Start from what runs now, so editing is "adjust this", never a blank page.
    const initial = route.effective.flatMap((ref) => {
      const i = ref.indexOf(":");
      return i > 0 ? [row(ref.slice(0, i), ref.slice(i + 1))] : [];
    });
    setRows(initial.length > 0 ? initial : [newRow()]);
  }

  function newRow(): Row {
    const c = connections[0];
    return row(c?.name ?? "", TEXT_TASKS.has(task) ? (c?.default_model ?? "") : "");
  }

  function loadCatalog(name: string) {
    const c = connections.find((x) => x.name === name);
    if (!c || catalogs[name]) return;
    setCatalogs((all) => ({ ...all, [name]: "loading" }));
    fetchModels(c.id, task === "asr" ? "speech" : "chat").then(
      (ids) => setCatalogs((all) => ({ ...all, [name]: ids })),
      () => setCatalogs((all) => ({ ...all, [name]: "failed" })),
    );
  }

  const update = (key: number, patch: Partial<Row>) =>
    setRows((rs) => rs && rs.map((r) => (r.key === key ? { ...r, ...patch } : r)));

  function move(index: number, by: -1 | 1) {
    setRows((rs) => {
      if (!rs) return rs;
      const next = [...rs];
      [next[index], next[index + by]] = [next[index + by], next[index]];
      return next;
    });
  }

  const refs = (rows ?? []).map((r) => `${r.connection}:${r.model.trim()}`);
  const incomplete = (rows ?? []).some((r) => !r.connection || !r.model.trim());
  const duplicate = new Set(refs).size !== refs.length;

  async function save() {
    setMessage(null);
    try {
      setRoute(
        await api<TaskRoute>(path, { method: "PUT", json: { models: refs } }),
      );
      setRows(null);
      setMessage({ ok: true, text: t("saved") });
    } catch (e) {
      setMessage({ ok: false, text: describe(e) });
    }
  }

  async function reset() {
    setMessage(null);
    try {
      await api(path, { method: "DELETE" });
      await load();
      setRows(null);
      setMessage({ ok: true, text: t("resetDone") });
    } catch (e) {
      setMessage({ ok: false, text: describe(e) });
    }
  }

  return (
    <Card data-testid={`route-${task}`} size={compact ? "sm" : undefined}>
      <CardHeader>
        <CardTitle>{t(`tasks.${task}.title`)}</CardTitle>
        <CardDescription>{t(`tasks.${task}.description`)}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {route && rows === null && (
          <>
            <p className="text-xs text-muted-foreground" data-testid={`route-source-${task}`}>
              {route.effective_source
                ? t(`source.${route.effective_source}`)
                : t(`tasks.${task}.none`)}
            </p>
            {route.effective.length > 0 && (
              <ol className="flex flex-col gap-1.5 text-sm" aria-label={t(`tasks.${task}.title`)}>
                {route.effective.map((m, i) => (
                  <li key={m} className="flex min-w-0 items-center gap-2">
                    <span className="w-4 shrink-0 text-right font-mono text-xs text-muted-foreground">
                      {i + 1}.
                    </span>
                    <span data-slot="route-ref" className="truncate font-mono text-[13px]">{m}</span>
                    {i > 0 && <Tag variant="outline">{t("fallback")}</Tag>}
                  </li>
                ))}
              </ol>
            )}
            <div className="flex gap-2">
              <Button
                size="sm"
                variant="outline"
                onClick={startEditing}
                disabled={connections.length === 0}
              >
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
        {rows !== null && (
          <>
            <p className="text-xs text-muted-foreground">{t("editHint")}</p>
            <ol
              className="flex flex-col divide-y border-y"
              aria-label={t("editLabel", { title: t(`tasks.${task}.title`) })}
            >
              {rows.map((r, i) => {
                const catalog = catalogs[r.connection];
                return (
                  <li key={r.key} className="flex flex-wrap items-center gap-2 py-2.5">
                    <span className="w-4 shrink-0 text-right font-mono text-xs text-muted-foreground">
                      {i + 1}.
                    </span>
                    <NativeSelect
                      aria-label={t("connection", { n: i + 1 })}
                      value={r.connection}
                      onChange={(e) => {
                        const c = connections.find((x) => x.name === e.target.value);
                        const model = TEXT_TASKS.has(task) ? (c?.default_model ?? "") : "";
                        update(r.key, { connection: e.target.value, model });
                      }}
                      className="w-36"
                    >
                      {/* A route may name a connection that was since deleted. */}
                      {!connections.some((c) => c.name === r.connection) && (
                        <option value={r.connection}>{r.connection}</option>
                      )}
                      {connections.map((c) => (
                        <option key={c.id} value={c.name}>
                          {c.name}
                        </option>
                      ))}
                    </NativeSelect>
                    <div className={cn("max-w-full min-w-40 flex-1", !compact && "md:max-w-80")}>
                      <AutocompleteInput
                        aria-label={t("model", { n: i + 1 })}
                        value={r.model}
                        onValueChange={(model) => update(r.key, { model })}
                        items={Array.isArray(catalog) ? catalog : []}
                        onOpenChange={(open) => open && loadCatalog(r.connection)}
                        empty={
                          catalog === "loading"
                            ? t("modelsLoading")
                            : catalog === "failed"
                              ? t("modelsFailed")
                              : t("modelsNoMatch")
                        }
                        autoComplete="off"
                        spellCheck={false}
                        className="font-mono"
                      />
                    </div>
                    <div className="ml-auto flex">
                      <Button
                        size="icon-sm"
                        variant="ghost"
                        aria-label={t("moveUp")}
                        disabled={i === 0}
                        onClick={() => move(i, -1)}
                      >
                        <ArrowUp />
                      </Button>
                      <Button
                        size="icon-sm"
                        variant="ghost"
                        aria-label={t("moveDown")}
                        disabled={i === rows.length - 1}
                        onClick={() => move(i, 1)}
                      >
                        <ArrowDown />
                      </Button>
                      <Button
                        size="icon-sm"
                        variant="ghost"
                        aria-label={t("remove")}
                        disabled={rows.length === 1}
                        onClick={() => setRows(rows.filter((x) => x.key !== r.key))}
                      >
                        <X />
                      </Button>
                    </div>
                  </li>
                );
              })}
            </ol>
            <div>
              <Button
                variant="link"
                disabled={rows.length >= MAX_ROWS}
                onClick={() => setRows([...rows, newRow()])}
              >
                <Plus />
                {t("addRow")}
              </Button>
            </div>
            {duplicate && (
              <ErrorText>{t("duplicate")}</ErrorText>
            )}
            <div className="flex gap-2">
              <Button size="sm" onClick={save} disabled={incomplete || duplicate}>
                {t("save")}
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setRows(null)}>
                {t("cancel")}
              </Button>
            </div>
          </>
        )}
        {message && (
          <p
            role="status"
            className={message.ok ? "text-sm text-success" : "text-sm text-destructive"}
          >
            {message.text}
          </p>
        )}
      </CardContent>
    </Card>
  );
}
