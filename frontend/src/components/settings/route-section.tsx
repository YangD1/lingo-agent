"use client";

import { ArrowDown, ArrowUp, Plus, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useRef, useState } from "react";

import { AutocompleteInput } from "@/components/ui/autocomplete";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { NativeSelect } from "@/components/ui/native-select";
import { Switch } from "@/components/ui/switch";
import { Tag } from "@/components/ui/tag";
import { ErrorText } from "@/components/ui/error-text";
import { api } from "@/lib/api";
import {
  type Connection,
  type TaskRoute,
  VOICE_LANGUAGES,
  type VoiceLanguage,
} from "@/lib/types";
import { cn } from "@/lib/utils";

import { fetchModels } from "./model-catalog";
import { useDescribeError } from "./use-describe-error";

const MAX_ROWS = 5; // the backend's limit on a route's fallback chain

/**
 * The routes the settings page edits: chat, the two that attachments need (ADR 0008 §5),
 * the background model that keeps the tutor's memory (ADR 0009), read-aloud and
 * pronunciation assessment (ADR 0028).
 */
export type RouteTask = "chat" | "reflect" | "vision" | "asr" | "tts" | "pronunciation";
const SECTION: Record<RouteTask, TaskRoute["section"]> = {
  chat: "llm",
  reflect: "llm",
  vision: "llm",
  asr: "asr",
  tts: "tts",
  pronunciation: "pronunciation",
};
// The speech sections have a single route each, stored under the task name "default".
const TASK_KEY: Record<RouteTask, string> = {
  chat: "chat",
  reflect: "reflect",
  vision: "vision",
  asr: "default",
  tts: "default",
  pronunciation: "default",
};
// A connection's default model is a chat model: only a good first guess for these.
const TEXT_TASKS = new Set<RouteTask>(["chat", "reflect"]);
// Azure assesses pronunciation through the same connection; the route names this model.
const PRONUNCIATION_MODEL = "pronunciation";

// The model a new row (or a row switched to `c`) starts with.
function firstModel(task: RouteTask, c: Connection | undefined): string {
  if (TEXT_TASKS.has(task)) return c?.default_model ?? "";
  return task === "pronunciation" && c?.kind === "azure_speech" ? PRONUNCIATION_MODEL : "";
}

// `off`: switched off in this route, kept in the chain but never called (ADR 0026).
// `voices` (read-aloud only): the voice for each language, over the built-in one.
type Voices = Partial<Record<VoiceLanguage, string>>;
type Row = { key: number; connection: string; model: string; off: boolean; voices: Voices };
// Why a row in the saved chain does or doesn't run.
type RowState = "on" | "off" | "connectionOff" | "connectionMissing";
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
  const [busy, setBusy] = useState(false);
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

  const row = (connection: string, model: string, off = false, voices: Voices = {}): Row => ({
    key: nextKey.current++,
    connection,
    model,
    off,
    voices,
  });
  // A read-aloud route's chosen voices, by "<connection>:<model>".
  const savedVoices = (route?.params.voices ?? {}) as Record<string, Voices>;

  // The chain as the tenant saved it (switched-off rows and rows whose connection is off
  // included), or what runs now when nothing is saved: the YAML route may name connections
  // this tenant doesn't have.
  const shown = route ? (route.overridden ? route.models : route.effective) : [];

  function stateOf(ref: string): RowState {
    if (route?.disabled.includes(ref)) return "off";
    const c = connections.find((x) => x.name === ref.slice(0, ref.indexOf(":")));
    if (!c) return "connectionMissing";
    return c.enabled ? "on" : "connectionOff";
  }

  function startEditing() {
    if (!route) return;
    setMessage(null);
    // Start from the chain shown, so editing is "adjust this", never a blank page.
    const initial = shown.flatMap((ref) => {
      const i = ref.indexOf(":");
      return i > 0
        ? [row(ref.slice(0, i), ref.slice(i + 1), route.disabled.includes(ref), savedVoices[ref])]
        : [];
    });
    setRows(initial.length > 0 ? initial : [newRow()]);
  }

  function newRow(): Row {
    // Only Azure assesses pronunciation (ADR 0028 §5): start from an Azure connection.
    const c =
      (task === "pronunciation" && connections.find((x) => x.kind === "azure_speech")) ||
      connections[0];
    return row(c?.name ?? "", firstModel(task, c));
  }

  async function put(
    models: string[],
    disabled: string[],
    voices?: Record<string, Voices>,
  ): Promise<boolean> {
    setMessage(null);
    setBusy(true);
    const params = voices && Object.keys(voices).length > 0 ? { params: { voices } } : {};
    try {
      setRoute(
        await api<TaskRoute>(path, { method: "PUT", json: { models, disabled, ...params } }),
      );
      return true;
    } catch (e) {
      setMessage({ ok: false, text: describe(e) });
      return false;
    } finally {
      setBusy(false);
    }
  }

  // Switching a row saves at once; on a route never saved, that saves the chain shown.
  async function toggle(ref: string, on: boolean) {
    if (!route) return;
    const disabled = on ? route.disabled.filter((x) => x !== ref) : [...route.disabled, ref];
    const voices = Object.fromEntries(
      Object.entries(savedVoices).filter(([voiceRef]) => shown.includes(voiceRef)),
    );
    if (await put(shown, disabled, voices)) {
      setMessage({ ok: true, text: t(on ? "switchedOn" : "switchedOff", { ref }) });
    }
  }

  function loadCatalog(name: string) {
    const c = connections.find((x) => x.name === name);
    if (!c || catalogs[name]) return;
    if (task === "pronunciation") {
      // Nothing to list: Azure's one assessment model, none elsewhere.
      const ids = c.kind === "azure_speech" ? [PRONUNCIATION_MODEL] : [];
      setCatalogs((all) => ({ ...all, [name]: ids }));
      return;
    }
    setCatalogs((all) => ({ ...all, [name]: "loading" }));
    const use =
      task === "asr" ? "speech" : task === "tts" ? (c.kind === "azure_speech" ? "all" : "tts") : "chat";
    fetchModels(c.id, use).then(
      // An Azure connection lists its assessment model with the voices; it reads nothing.
      (ids) =>
        setCatalogs((all) => ({
          ...all,
          [name]: task === "tts" ? ids.filter((id) => id !== PRONUNCIATION_MODEL) : ids,
        })),
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
    const disabled = (rows ?? []).flatMap((r, i) => (r.off ? [refs[i]] : []));
    const voices = Object.fromEntries(
      (rows ?? []).flatMap((r, i) => {
        const chosen = Object.fromEntries(
          Object.entries(r.voices).flatMap(([lang, voice]) =>
            voice?.trim() ? [[lang, voice.trim()]] : [],
          ),
        );
        return Object.keys(chosen).length > 0 ? [[refs[i], chosen]] : [];
      }),
    );
    if (await put(refs, disabled, voices)) {
      setRows(null);
      setMessage({ ok: true, text: t("saved") });
    }
  }

  // "Fallback" marks the rows after the first one that actually runs.
  const firstOn = shown.findIndex((ref) => stateOf(ref) === "on");
  const allOff = !!route && route.effective.length === 0 && route.disabled.length > 0;

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
            {allOff ? (
              <ErrorText size="xs">{t("allOff")}</ErrorText>
            ) : (
              <p className="text-xs text-muted-foreground" data-testid={`route-source-${task}`}>
                {route.effective_source
                  ? t(`source.${route.effective_source}`)
                  : t(`tasks.${task}.none`)}
              </p>
            )}
            {shown.length > 0 && (
              <ol className="flex flex-col gap-1.5 text-sm" aria-label={t(`tasks.${task}.title`)}>
                {shown.map((m, i) => {
                  const state = stateOf(m);
                  return (
                    <li
                      key={m}
                      data-state={state}
                      className="flex min-w-0 items-center gap-2"
                    >
                      <span className="w-4 shrink-0 text-right font-mono text-xs text-muted-foreground">
                        {i + 1}.
                      </span>
                      <span
                        data-slot="route-ref"
                        className={cn(
                          "truncate font-mono text-[13px]",
                          state !== "on" && "text-muted-foreground line-through",
                        )}
                      >
                        {m}
                      </span>
                      {state === "on" && i > firstOn && <Tag variant="outline">{t("fallback")}</Tag>}
                      {state === "off" && <Tag variant="outline">{t("rowOff")}</Tag>}
                      {state === "connectionOff" && (
                        <Tag variant="outline">{t("connectionOff")}</Tag>
                      )}
                      {state === "connectionMissing" && (
                        <Tag variant="outline">{t("connectionMissing")}</Tag>
                      )}
                      {task === "tts" && savedVoices[m] && (
                        <span className="truncate text-xs text-muted-foreground">
                          {VOICE_LANGUAGES.flatMap((lang) =>
                            savedVoices[m]?.[lang]
                              ? [`${t(`voiceLang.${lang}`)} ${savedVoices[m][lang]}`]
                              : [],
                          ).join(" · ")}
                        </span>
                      )}
                      <Switch
                        size="sm"
                        className="ml-auto"
                        aria-label={t("rowSwitch", { ref: m })}
                        checked={state !== "off"}
                        disabled={busy}
                        onCheckedChange={(on) => void toggle(m, on)}
                      />
                    </li>
                  );
                })}
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
            {task === "tts" && <p className="text-xs text-muted-foreground">{t("voicesHint")}</p>}
            <ol
              className="flex flex-col divide-y border-y"
              aria-label={t("editLabel", { title: t(`tasks.${task}.title`) })}
            >
              {rows.map((r, i) => {
                const catalog = catalogs[r.connection];
                return (
                  <li
                    key={r.key}
                    className={cn(
                      "flex flex-wrap items-center gap-2 py-2.5",
                      r.off && "opacity-60",
                    )}
                  >
                    <span className="w-4 shrink-0 text-right font-mono text-xs text-muted-foreground">
                      {i + 1}.
                    </span>
                    <NativeSelect
                      aria-label={t("connection", { n: i + 1 })}
                      value={r.connection}
                      onChange={(e) => {
                        const c = connections.find((x) => x.name === e.target.value);
                        update(r.key, { connection: e.target.value, model: firstModel(task, c) });
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
                    <div className="ml-auto flex items-center">
                      <Switch
                        size="sm"
                        className="mr-1.5"
                        aria-label={t("rowSwitch", { ref: refs[i] })}
                        checked={!r.off}
                        onCheckedChange={(on) => update(r.key, { off: !on })}
                      />
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
                    {task === "tts" && (
                      <VoiceInputs
                        index={i}
                        voices={r.voices}
                        defaults={route?.default_voices?.[refs[i]]}
                        catalog={
                          connections.find((c) => c.name === r.connection)?.kind ===
                            "azure_speech" && Array.isArray(catalog)
                            ? catalog
                            : []
                        }
                        onOpen={() => loadCatalog(r.connection)}
                        onChange={(voices) => update(r.key, { voices })}
                      />
                    )}
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
              <Button size="sm" onClick={save} disabled={busy || incomplete || duplicate}>
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

/**
 * The voice a read-aloud model reads each language with (Q54b). Empty means the built-in
 * voice, shown as the placeholder; an Azure connection offers its voices for the language.
 */
function VoiceInputs({
  index,
  voices,
  defaults,
  catalog,
  onOpen,
  onChange,
}: {
  index: number;
  voices: Voices;
  /** The built-in voices, known once the route is saved with this model. */
  defaults: Record<VoiceLanguage, string | null> | undefined;
  catalog: string[];
  onOpen: () => void;
  onChange: (voices: Voices) => void;
}) {
  const t = useTranslations("settings.route");
  return (
    <div className="grid w-full gap-2 pl-6 sm:grid-cols-3" data-testid={`voices-${index + 1}`}>
      {VOICE_LANGUAGES.map((lang) => {
        const builtIn = defaults?.[lang];
        return (
          <div key={lang} className="flex min-w-0 flex-col gap-1">
            <span className="text-xs text-muted-foreground">{t(`voiceLang.${lang}`)}</span>
            <AutocompleteInput
              aria-label={t("voice", { lang: t(`voiceLang.${lang}`), n: index + 1 })}
              value={voices[lang] ?? ""}
              onValueChange={(voice) => onChange({ ...voices, [lang]: voice })}
              items={catalog.filter((id) => id.startsWith(`${lang}-`) || id.includes("Multilingual"))}
              onOpenChange={(open) => open && onOpen()}
              empty={t("modelsNoMatch")}
              placeholder={
                defaults === undefined
                  ? t("voiceBuiltIn")
                  : builtIn
                    ? t("voiceDefault", { voice: builtIn })
                    : t("voiceNone")
              }
              autoComplete="off"
              spellCheck={false}
              className="font-mono text-xs"
            />
          </div>
        );
      })}
    </div>
  );
}
