"use client";

import { useFormatter, useTranslations } from "next-intl";
import { type FormEvent, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { NativeSelect } from "@/components/ui/native-select";
import { api } from "@/lib/api";
import {
  type Connection,
  type ConnectionTest,
  PROVIDER_KINDS,
  type Presets,
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
                defaultModel={presets.presets.find((p) => p.name === c.name)?.models[0] ?? ""}
                onUpdated={(next) => onChange(connections.map((x) => (x.id === next.id ? next : x)))}
                onDeleted={() => onChange(connections.filter((x) => x.id !== c.id))}
              />
            ))}
          </ul>
        )}
        <AddConnectionForm
          presets={presets}
          existing={connections}
          onCreated={(c) => onChange([...connections, c])}
        />
      </CardContent>
    </Card>
  );
}

function ConnectionItem({
  connection: c,
  defaultModel,
  onUpdated,
  onDeleted,
}: {
  connection: Connection;
  defaultModel: string;
  onUpdated: (c: Connection) => void;
  onDeleted: () => void;
}) {
  const t = useTranslations("settings.connections");
  const format = useFormatter();
  const describe = useDescribeError();
  const [model, setModel] = useState(defaultModel);
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

  const test = () =>
    run(async () => {
      const r = await api<ConnectionTest>(`/tenant/connections/${c.id}/test`, {
        method: "POST",
        json: { model },
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
    });

  const remove = () =>
    run(async () => {
      if (!window.confirm(t("confirmDelete", { name: c.name }))) return;
      await api(`/tenant/connections/${c.id}`, { method: "DELETE" });
      onDeleted();
    });

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
      <div className="flex flex-wrap items-center gap-2">
        <Input
          aria-label={t("testModel")}
          placeholder={t("testModel")}
          value={model}
          onChange={(e) => setModel(e.target.value)}
          className="h-8 w-48"
        />
        <Button size="sm" variant="outline" onClick={test} disabled={busy || !model.trim()}>
          {t("test")}
        </Button>
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
