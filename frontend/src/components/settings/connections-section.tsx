"use client";

import { useFormatter, useTranslations } from "next-intl";
import { type FormEvent, useEffect, useState } from "react";

import { AutocompleteInput } from "@/components/ui/autocomplete";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { NativeSelect } from "@/components/ui/native-select";
import { ApiError, api } from "@/lib/api";
import { chatModelIds, modelsOfRefs, recommendModel } from "@/lib/models";
import {
  type Connection,
  type ConnectionTest,
  type ModelList,
  PROVIDER_KINDS,
  type Presets,
  type TaskRoute,
} from "@/lib/types";

import { useDescribeError } from "./use-describe-error";

const CUSTOM = "__custom__";

type Props = {
  presets: Presets;
  connections: Connection[];
  onChange: (connections: Connection[]) => void;
};

export function ConnectionsSection({ presets, connections, onChange }: Props) {
  const t = useTranslations("settings.connections");
  const [justAdded, setJustAdded] = useState<string | null>(null);
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("title")}</CardTitle>
        <CardDescription>{t("description")}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-6">
        {connections.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t("none")}</p>
        ) : (
          <ul className="flex flex-col gap-3" aria-label={t("title")}>
            {connections.map((c) => (
              <ConnectionItem
                key={c.id}
                connection={c}
                presetModels={presets.presets.find((p) => p.name === c.name)?.models ?? []}
                loadOnMount={c.id === justAdded}
                onUpdated={(next) => onChange(connections.map((x) => (x.id === next.id ? next : x)))}
                onDeleted={() => onChange(connections.filter((x) => x.id !== c.id))}
              />
            ))}
          </ul>
        )}
        <AddConnectionForm
          presets={presets}
          existing={connections}
          onCreated={(c) => {
            // Without a default model it can't chat yet: fetch its models to pick one.
            if (!c.default_model) setJustAdded(c.id);
            onChange([...connections, c]);
          }}
        />
      </CardContent>
    </Card>
  );
}

function ConnectionItem({
  connection: c,
  presetModels,
  loadOnMount,
  onUpdated,
  onDeleted,
}: {
  connection: Connection;
  presetModels: string[];
  loadOnMount: boolean;
  onUpdated: (c: Connection) => void;
  onDeleted: () => void;
}) {
  const t = useTranslations("settings.connections");
  const format = useFormatter();
  const describe = useDescribeError();
  const [model, setModel] = useState(c.default_model ?? "");
  const [catalog, setCatalog] = useState<Catalog>({ state: loadOnMount ? "loading" : "idle" });
  const [newKey, setNewKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; text: string } | null>(null);

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setResult(null);
    try {
      await action();
    } catch (e) {
      setResult({ ok: false, text: describe(e) });
    } finally {
      setBusy(false);
    }
  }

  // Listing the models also proves the key works, and costs no tokens (ADR 0007 §1).
  function loadModels() {
    setCatalog({ state: "loading" });
    void fetchModels();
  }
  async function fetchModels() {
    try {
      const [list, routes] = await Promise.all([
        api<ModelList>(`/tenant/connections/${c.id}/models`),
        api<TaskRoute[]>("/tenant/routes").catch(() => []),
      ]);
      const ids = chatModelIds(list.models);
      setCatalog({ state: "ok", ids });
      if (!c.default_model) {
        const chat = routes.find((r) => r.section === "llm" && r.task === "chat");
        const preferred = [...presetModels, ...modelsOfRefs(chat?.models ?? [])];
        setModel((current) => current || recommendModel(ids, preferred));
      }
    } catch (e) {
      // model_list_failed carries the vendor's own reason (e.g. "HTTP 401: …"), which is
      // what the user needs; other errors get the usual localized text.
      const reason = e instanceof ApiError && e.code === "model_list_failed" ? e.message : describe(e);
      setCatalog({ state: "failed", error: reason });
    }
  }
  // eslint-disable-next-line react-hooks/exhaustive-deps -- once, for a just-added connection
  useEffect(() => void (loadOnMount && fetchModels()), []);

  const saveModel = () =>
    run(async () => {
      onUpdated(
        await api<Connection>(`/tenant/connections/${c.id}`, {
          method: "PATCH",
          json: { default_model: model.trim() },
        }),
      );
      setResult({ ok: true, text: t("modelSaved") });
    });

  // Tests what's in the box, saved or not, so a model can be tried before saving it.
  const test = () =>
    run(async () => {
      const r = await api<ConnectionTest>(`/tenant/connections/${c.id}/test`, {
        method: "POST",
        json: { model: model.trim() },
      });
      setResult(
        r.ok
          ? { ok: true, text: t("testOk", { ms: r.latency_ms }) }
          : { ok: false, text: t("testFailed", { error: r.error ?? "" }) },
      );
      // The backend recorded last_verified_at / last_error; show them.
      const all = await api<Connection[]>("/tenant/connections");
      const updated = all.find((x) => x.id === c.id);
      if (updated) onUpdated(updated);
    });

  const saveKey = () =>
    run(async () => {
      onUpdated(
        await api<Connection>(`/tenant/connections/${c.id}`, {
          method: "PATCH",
          json: { api_key: newKey },
        }),
      );
      setNewKey("");
      setResult({ ok: true, text: t("keySaved") });
      if (catalog.state !== "idle") loadModels(); // the old list may have failed on the old key
    });

  const remove = () =>
    run(async () => {
      if (!window.confirm(t("confirmDelete", { name: c.name }))) return;
      await api(`/tenant/connections/${c.id}`, { method: "DELETE" });
      onDeleted();
    });

  const saved = c.default_model ?? "";
  return (
    <li className="flex flex-col gap-3 rounded-lg border p-3" data-testid={`connection-${c.name}`}>
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="font-medium">{c.name}</span>
        <span className="text-xs text-muted-foreground">{c.kind}</span>
        <span className="truncate text-xs text-muted-foreground">{c.base_url}</span>
        <span className="ml-auto text-xs text-muted-foreground">
          {c.has_api_key ? t("keyHint", { hint: c.key_hint ?? "" }) : t("noKey")}
        </span>
      </div>
      <p className="text-xs text-muted-foreground">
        {c.last_error
          ? t("lastError", { error: c.last_error })
          : c.last_verified_at
            ? t("lastVerified", { when: format.relativeTime(new Date(c.last_verified_at)) })
            : t("neverTested")}
      </p>
      <div className="flex flex-col gap-2">
        <Label htmlFor={`model-${c.id}`}>{t("defaultModel")}</Label>
        <div className="flex flex-wrap items-center gap-2">
          <div className="w-72 max-w-full">
            <AutocompleteInput
              id={`model-${c.id}`}
              value={model}
              onValueChange={setModel}
              items={catalog.state === "ok" ? catalog.ids : []}
              onOpenChange={(open) => {
                if (open && catalog.state === "idle") loadModels();
              }}
              empty={catalog.state === "loading" ? t("modelsLoading") : t("modelsNoMatch")}
              placeholder={t("modelPlaceholder")}
              autoComplete="off"
              spellCheck={false}
              className="font-mono"
            />
          </div>
          <Button
            size="sm"
            onClick={saveModel}
            disabled={busy || model.trim() === saved}
          >
            {t("saveModel")}
          </Button>
          <Button size="sm" variant="outline" onClick={test} disabled={busy || !model.trim()}>
            {t("test")}
          </Button>
        </div>
        <CatalogStatus catalog={catalog} hasDefault={saved !== ""} onRetry={loadModels} />
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Input
          type="password"
          aria-label={t("newKey")}
          placeholder={t("newKey")}
          value={newKey}
          onChange={(e) => setNewKey(e.target.value)}
          autoComplete="off"
          className="h-8 w-48"
        />
        <Button size="sm" variant="outline" onClick={saveKey} disabled={busy || !newKey.trim()}>
          {t("saveKey")}
        </Button>
        <Button size="sm" variant="ghost" onClick={remove} disabled={busy} className="ml-auto">
          {t("delete")}
        </Button>
      </div>
      {result && (
        <p
          role="status"
          className={result.ok ? "text-sm text-emerald-600" : "text-sm text-destructive"}
        >
          {result.text}
        </p>
      )}
    </li>
  );
}

type Catalog =
  | { state: "idle" | "loading" }
  | { state: "ok"; ids: string[] }
  | { state: "failed"; error: string };

function CatalogStatus({
  catalog,
  hasDefault,
  onRetry,
}: {
  catalog: Catalog;
  hasDefault: boolean;
  onRetry: () => void;
}) {
  const t = useTranslations("settings.connections");
  if (catalog.state === "failed") {
    return (
      <p className="text-xs text-destructive" data-testid="model-list-status">
        {t("modelsFailed", { error: catalog.error })}{" "}
        <button type="button" onClick={onRetry} className="underline underline-offset-2">
          {t("retry")}
        </button>
      </p>
    );
  }
  const text =
    catalog.state === "loading"
      ? t("modelsLoading")
      : catalog.state === "ok"
        ? catalog.ids.length > 0
          ? t("modelsFound", { count: catalog.ids.length })
          : t("modelsFoundNone")
        : hasDefault
          ? null
          : t("noDefaultModel");
  return text && (
    <p className="text-xs text-muted-foreground" data-testid="model-list-status">
      {text}
    </p>
  );
}

function AddConnectionForm({
  presets,
  existing,
  onCreated,
}: {
  presets: Presets;
  existing: Connection[];
  onCreated: (c: Connection) => void;
}) {
  const t = useTranslations("settings.connections");
  const describe = useDescribeError();
  // Presets already added can't be added again (the name is the connection's identity).
  const available = presets.presets.filter((p) => !existing.some((c) => c.name === p.name));
  const [choice, setChoice] = useState(available[0]?.name ?? CUSTOM);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const preset = available.find((p) => p.name === choice);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const apiKey = String(data.get("api_key") ?? "") || undefined;
    const body = preset
      ? { preset: preset.name, api_key: apiKey }
      : {
          name: String(data.get("name")),
          kind: String(data.get("kind")),
          base_url: String(data.get("base_url")),
          api_key: apiKey,
        };
    setBusy(true);
    setError(null);
    try {
      onCreated(await api<Connection>("/tenant/connections", { method: "POST", json: body }));
      form.reset();
      setChoice(CUSTOM);
    } catch (e) {
      setError(describe(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-3 border-t pt-4" aria-label={t("add")}>
      <h3 className="text-sm font-medium">{t("add")}</h3>
      <div className="flex flex-col gap-2">
        <Label htmlFor="provider">{t("provider")}</Label>
        <NativeSelect
          id="provider"
          value={choice}
          onChange={(e) => setChoice(e.target.value)}
          className="w-64"
        >
          {available.map((p) => (
            <option key={p.name} value={p.name}>
              {p.label ?? p.name}
            </option>
          ))}
          <option value={CUSTOM}>{t("custom")}</option>
        </NativeSelect>
        {preset && <p className="text-xs text-muted-foreground">{preset.base_url}</p>}
      </div>
      {!preset && (
        <div className="grid gap-3 sm:grid-cols-3">
          <div className="flex flex-col gap-2">
            <Label htmlFor="conn-name">{t("name")}</Label>
            <Input id="conn-name" name="name" required pattern="[a-z0-9][a-z0-9_\-]{0,63}" maxLength={64} />
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="conn-kind">{t("kind")}</Label>
            <NativeSelect id="conn-kind" name="kind" defaultValue="openai_compatible">
              {PROVIDER_KINDS.map((k) => (
                <option key={k} value={k}>
                  {k}
                </option>
              ))}
            </NativeSelect>
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="conn-base-url">{t("baseUrl")}</Label>
            <Input id="conn-base-url" name="base_url" type="url" required />
          </div>
        </div>
      )}
      <div className="flex flex-col gap-2">
        <Label htmlFor="api_key">{t("apiKey")}</Label>
        <Input id="api_key" name="api_key" type="password" autoComplete="off" className="w-96 max-w-full" />
        <p className="text-xs text-muted-foreground">{t("apiKeyHint")}</p>
      </div>
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
      <div>
        <Button type="submit" disabled={busy}>
          {t("addSubmit")}
        </Button>
      </div>
    </form>
  );
}
