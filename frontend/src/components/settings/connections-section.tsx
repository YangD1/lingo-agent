"use client";

import { CircleAlert, CircleCheck, Pencil, Plus, Trash2 } from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";
import { type FormEvent, useEffect, useState } from "react";

import { AutocompleteInput } from "@/components/ui/autocomplete";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { InlineConfirm } from "@/components/ui/inline-confirm";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { NativeSelect } from "@/components/ui/native-select";
import { Tag } from "@/components/ui/tag";
import { api } from "@/lib/api";
import { modelsOfRefs, recommendModel } from "@/lib/models";
import {
  type Connection,
  type ConnectionTest,
  PROVIDER_KINDS,
  type Presets,
  type TaskRoute,
} from "@/lib/types";

import { fetchModels as fetchConnectionModels, modelListFailure } from "./model-catalog";
import { useDescribeError } from "./use-describe-error";

const CUSTOM = "__custom__";

// "auto" lets the backend guess from the model's name and the tenant's routes.
const TEST_AS = {
  auto: "testAsAuto",
  chat: "testAsChat",
  asr: "testAsAsr",
  vision: "testAsVision",
} as const;
const TEST_OK = { chat: "testOk", asr: "testOkAsr", vision: "testOkVision" } as const;

type Props = {
  presets: Presets;
  connections: Connection[];
  onChange: (connections: Connection[]) => void;
};

export function ConnectionsSection({ presets, connections, onChange }: Props) {
  const t = useTranslations("settings.connections");
  const [justAdded, setJustAdded] = useState<string | null>(null);
  return (
    <Card id="connections" className="scroll-mt-14 lg:scroll-mt-4">
      <CardHeader>
        <CardTitle>{t("title")}</CardTitle>
        <CardDescription>{t("description")}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-5">
        {connections.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t("none")}</p>
        ) : (
          <ul className="flex flex-col gap-3" aria-label={t("title")}>
            {connections.map((c) => (
              <ConnectionItem
                key={c.id}
                connection={c}
                presetModels={presets.presets.find((p) => p.name === c.name)?.models ?? []}
                isPreset={presets.presets.some((p) => p.name === c.name)}
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
  isPreset,
  loadOnMount,
  onUpdated,
  onDeleted,
}: {
  connection: Connection;
  presetModels: string[];
  isPreset: boolean;
  loadOnMount: boolean;
  onUpdated: (c: Connection) => void;
  onDeleted: () => void;
}) {
  const t = useTranslations("settings.connections");
  const format = useFormatter();
  const describe = useDescribeError();
  const [model, setModel] = useState(c.default_model ?? "");
  const [catalog, setCatalog] = useState<Catalog>({ state: loadOnMount ? "loading" : "idle" });
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; text: string } | null>(null);
  const [testAs, setTestAs] = useState<keyof typeof TEST_AS>("auto");

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
      const [ids, routes] = await Promise.all([
        fetchConnectionModels(c.id),
        api<TaskRoute[]>("/tenant/routes").catch(() => []),
      ]);
      setCatalog({ state: "ok", ids });
      if (!c.default_model) {
        const chat = routes.find((r) => r.section === "llm" && r.task === "chat");
        const preferred = [...presetModels, ...modelsOfRefs(chat?.models ?? [])];
        setModel((current) => current || recommendModel(ids, preferred));
      }
    } catch (e) {
      setCatalog({ state: "failed", error: modelListFailure(e, describe) });
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
        json: { model: model.trim(), ...(testAs === "auto" ? {} : { purpose: testAs }) },
      });
      setResult(
        r.ok
          ? { ok: true, text: t(TEST_OK[r.purpose], { ms: r.latency_ms }) }
          : {
              ok: false,
              text:
                r.error_code === "asr_not_supported"
                  ? t("asrNotSupported")
                  : r.error_code === "vision_not_supported"
                    ? t("visionNotSupported")
                    : t("testFailed", { error: r.error ?? "" }),
            },
      );
      // The backend recorded last_verified_at / last_error; show them.
      const all = await api<Connection[]>("/tenant/connections");
      const updated = all.find((x) => x.id === c.id);
      if (updated) onUpdated(updated);
    });

  const saveEdit = (patch: ConnectionPatch) =>
    run(async () => {
      onUpdated(
        await api<Connection>(`/tenant/connections/${c.id}`, { method: "PATCH", json: patch }),
      );
      setEditing(false);
      setResult({ ok: true, text: t("edited") });
      // A new endpoint or key may list different models (or list them at all, now).
      if (catalog.state !== "idle" && (patch.kind || patch.base_url || patch.api_key)) {
        loadModels();
      }
    });

  const remove = () =>
    run(async () => {
      await api(`/tenant/connections/${c.id}`, { method: "DELETE" });
      onDeleted();
    });

  const saved = c.default_model ?? "";
  return (
    <li className="flex flex-col gap-3 rounded-lg border p-3.5" data-testid={`connection-${c.name}`}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-semibold">{c.name}</span>
        <Tag variant="outline">{c.kind}</Tag>
        {!editing && (
          <div className="ml-auto flex items-center">
            <Button size="sm" variant="ghost" onClick={() => setEditing(true)} disabled={busy}>
              <Pencil />
              {t("edit")}
            </Button>
            <InlineConfirm
              question={t("confirmDelete", { name: c.name })}
              confirmLabel={t("delete")}
              onConfirm={() => void remove()}
            >
              {(ask) => (
                <Button size="sm" variant="ghost" onClick={ask} disabled={busy}>
                  <Trash2 />
                  {t("delete")}
                </Button>
              )}
            </InlineConfirm>
          </div>
        )}
      </div>
      <dl className="grid gap-x-6 gap-y-2 text-[13px] md:grid-cols-[minmax(0,1.4fr)_minmax(0,0.8fr)_minmax(0,1.4fr)]">
        <div className="flex min-w-0 flex-col gap-0.5">
          <dt className="text-xs text-muted-foreground">{t("address")}</dt>
          <dd className="truncate font-mono" title={c.base_url}>
            {c.base_url}
          </dd>
        </div>
        <div className="flex min-w-0 flex-col gap-0.5">
          <dt className="text-xs text-muted-foreground">{t("key")}</dt>
          <dd className="truncate font-mono">
            {c.has_api_key ? (c.key_hint ?? "") : t("noKey")}
          </dd>
        </div>
        <div className="flex min-w-0 flex-col gap-0.5">
          <dt className="text-xs text-muted-foreground">{t("lastTest")}</dt>
          <dd>
            {c.last_error ? (
              <span className="flex items-start gap-1.5 text-destructive">
                <CircleAlert className="mt-0.5 size-3.5 shrink-0" />
                <span className="line-clamp-2 break-all" title={c.last_error}>
                  {c.last_error}
                </span>
              </span>
            ) : c.last_verified_at ? (
              <span className="flex items-center gap-1.5 text-success">
                <CircleCheck className="size-3.5 shrink-0" />
                {t("lastOk", { when: format.relativeTime(new Date(c.last_verified_at)) })}
              </span>
            ) : (
              <span className="text-muted-foreground">{t("neverTested")}</span>
            )}
          </dd>
        </div>
      </dl>
      <div className="flex flex-col gap-2">
        <Label htmlFor={`model-${c.id}`}>{t("defaultModel")}</Label>
        <div className="flex flex-wrap items-center gap-2">
          <div className="max-w-full min-w-48 flex-1 md:max-w-80">
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
            variant="outline"
            onClick={saveModel}
            disabled={busy || model.trim() === saved}
          >
            {t("saveModel")}
          </Button>
          <Button variant="outline" onClick={test} disabled={busy || !model.trim()}>
            {t("test")}
          </Button>
          <NativeSelect
            aria-label={t("testAs")}
            title={t("testAs")}
            value={testAs}
            onChange={(e) => setTestAs(e.target.value as keyof typeof TEST_AS)}
          >
            {Object.entries(TEST_AS).map(([value, label]) => (
              <option key={value} value={value}>
                {t(label)}
              </option>
            ))}
          </NativeSelect>
        </div>
        <p className="text-xs text-muted-foreground">{t("defaultModelHint")}</p>
        <CatalogStatus catalog={catalog} hasDefault={saved !== ""} onRetry={loadModels} />
      </div>
      {editing && (
        <EditConnectionForm
          connection={c}
          isPreset={isPreset}
          busy={busy}
          onSave={saveEdit}
          onCancel={() => setEditing(false)}
        />
      )}
      {result && (
        <p
          role="status"
          className={result.ok ? "text-sm text-success" : "text-sm text-destructive"}
        >
          {result.text}
        </p>
      )}
    </li>
  );
}

type ConnectionPatch = { name?: string; kind?: string; base_url?: string; api_key?: string };

/** Edits every field; only what changed is sent (ADR 0007 §4). */
function EditConnectionForm({
  connection: c,
  isPreset,
  busy,
  onSave,
  onCancel,
}: {
  connection: Connection;
  isPreset: boolean;
  busy: boolean;
  onSave: (patch: ConnectionPatch) => void;
  onCancel: () => void;
}) {
  const t = useTranslations("settings.connections");
  const [name, setName] = useState(c.name);
  const [kind, setKind] = useState<string>(c.kind);
  const [baseUrl, setBaseUrl] = useState(c.base_url);
  const [apiKey, setApiKey] = useState("");
  const id = (field: string) => `edit-${c.id}-${field}`;

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const patch: ConnectionPatch = {};
    if (name.trim() !== c.name) patch.name = name.trim();
    if (kind !== c.kind) patch.kind = kind;
    if (baseUrl.trim() !== c.base_url) patch.base_url = baseUrl.trim();
    if (apiKey) patch.api_key = apiKey;
    if (Object.keys(patch).length === 0) onCancel();
    else onSave(patch);
  }

  return (
    <form
      onSubmit={submit}
      className="flex flex-col gap-3 rounded-md bg-muted/40 p-3"
      aria-label={t("editTitle", { name: c.name })}
    >
      <div className="grid gap-3 sm:grid-cols-3">
        <div className="flex flex-col gap-2">
          <Label htmlFor={id("name")}>{t("name")}</Label>
          <Input
            id={id("name")}
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
            pattern="[a-z0-9][a-z0-9_\-]{0,63}"
            maxLength={64}
          />
        </div>
        <div className="flex flex-col gap-2">
          <Label htmlFor={id("kind")}>{t("kind")}</Label>
          <NativeSelect id={id("kind")} value={kind} onChange={(e) => setKind(e.target.value)}>
            {PROVIDER_KINDS.map((k) => (
              <option key={k} value={k}>
                {k}
              </option>
            ))}
          </NativeSelect>
        </div>
        <div className="flex flex-col gap-2">
          <Label htmlFor={id("base-url")}>{t("baseUrl")}</Label>
          <Input
            id={id("base-url")}
            type="url"
            value={baseUrl}
            onChange={(e) => setBaseUrl(e.target.value)}
            required
          />
        </div>
      </div>
      {isPreset && name.trim() !== c.name && (
        <p className="text-xs text-warning">{t("renamePresetHint")}</p>
      )}
      <div className="flex flex-col gap-2">
        <Label htmlFor={id("key")}>{t("newKey")}</Label>
        <Input
          id={id("key")}
          type="password"
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
          placeholder={t("newKeyPlaceholder")}
          autoComplete="off"
          className="w-96 max-w-full"
        />
      </div>
      <div className="flex gap-2">
        <Button type="submit" size="sm" disabled={busy}>
          {t("saveEdit")}
        </Button>
        <Button type="button" size="sm" variant="ghost" onClick={onCancel}>
          {t("cancel")}
        </Button>
      </div>
    </form>
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
      <h3 className="text-sm font-semibold">{t("add")}</h3>
      <div className="grid gap-3 md:grid-cols-2">
        <div className="flex flex-col gap-2">
          <Label htmlFor="provider">{t("provider")}</Label>
          <NativeSelect id="provider" value={choice} onChange={(e) => setChoice(e.target.value)}>
            {available.map((p) => (
              <option key={p.name} value={p.name}>
                {p.label ?? p.name}
              </option>
            ))}
            <option value={CUSTOM}>{t("custom")}</option>
          </NativeSelect>
          {preset && (
            <p className="truncate font-mono text-xs text-muted-foreground">{preset.base_url}</p>
          )}
        </div>
        {!preset && (
          <>
            <div className="flex flex-col gap-2">
              <Label htmlFor="conn-name">{t("name")}</Label>
              <Input
                id="conn-name"
                name="name"
                required
                pattern="[a-z0-9][a-z0-9_\-]{0,63}"
                maxLength={64}
              />
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
          </>
        )}
        <div className="flex flex-col gap-2 md:col-span-2">
          <Label htmlFor="api_key">{t("apiKey")}</Label>
          <Input id="api_key" name="api_key" type="password" autoComplete="off" />
          <p className="text-xs text-muted-foreground">{t("apiKeyHint")}</p>
        </div>
      </div>
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
      <div>
        <Button type="submit" disabled={busy}>
          <Plus />
          {t("addSubmit")}
        </Button>
      </div>
    </form>
  );
}
