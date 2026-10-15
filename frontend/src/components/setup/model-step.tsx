"use client";

import { CheckCircle2Icon } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import { fetchModels, modelListFailure } from "@/components/settings/model-catalog";
import { JoinPanel } from "@/components/settings/membership-section";
import { useDescribeError } from "@/components/settings/use-describe-error";
import { Callout } from "@/components/ui/callout";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Segmented } from "@/components/ui/segmented";
import { Select } from "@/components/ui/select";
import { api } from "@/lib/api";
import { recommendModel } from "@/lib/models";
import type { Connection, Preset, Presets } from "@/lib/types";

import { LeaveLink, type StepNav, StepFrame } from "./step-frame";

// Presets for speech only (ADR 0008, 0028, 0030): the guide sets up chat; these stay in settings.
const SPEECH_KINDS: ReadonlySet<string> = new Set(["azure_speech", "gemini"]);
const SPEECH_PRESETS: ReadonlySet<string> = new Set(["stepfun", "groq", "siliconflow", "speaches"]);

export function chatPresets(presets: Preset[]): Preset[] {
  return presets.filter((p) => !SPEECH_KINDS.has(p.kind) && !SPEECH_PRESETS.has(p.name));
}

/**
 * Step 2: one chat model, by pasting a key or joining a main account (ADR 0042 §2). The key is
 * checked by listing the vendor's models, which costs no tokens (ADR 0007 §1).
 */
export function ModelStep({ ready, nav }: { ready: boolean; nav: StepNav }) {
  const t = useTranslations("setup.steps.model");
  const describe = useDescribeError();
  const [mode, setMode] = useState<"key" | "invite">("key");
  const [presets, setPresets] = useState<Preset[] | null>(null);
  const [connections, setConnections] = useState<Connection[]>([]);
  const [choice, setChoice] = useState("");
  const [apiKey, setApiKey] = useState("");
  // The model the guide just connected; shown before moving on.
  const [connected, setConnected] = useState<{ provider: string; model: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (ready) return;
    Promise.all([api<Presets>("/provider-presets"), api<Connection[]>("/tenant/connections")]).then(
      ([found, existing]) => {
        const usable = chatPresets(found.presets);
        setPresets(usable);
        setConnections(existing);
        setChoice(usable[0]?.name ?? "");
      },
      (e: unknown) => setError(describe(e)),
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps -- load once
  }, [ready]);

  const preset = presets?.find((p) => p.name === choice);

  async function connect() {
    if (!preset) return;
    setBusy(true);
    setError(null);
    try {
      // Tried before with a wrong key: put the new key on the same connection.
      const existing = connections.find((c) => c.name === preset.name);
      const key = apiKey.trim() || undefined;
      let connection = existing
        ? await api<Connection>(`/tenant/connections/${existing.id}`, {
            method: "PATCH",
            json: key ? { api_key: key } : {},
          })
        : await api<Connection>("/tenant/connections", {
            method: "POST",
            json: { preset: preset.name, api_key: key },
          });
      setConnections((all) => [...all.filter((c) => c.id !== connection.id), connection]);
      let ids: string[];
      try {
        ids = await fetchModels(connection.id, "chat");
      } catch (e) {
        setError(t("keyFailed", { error: modelListFailure(e, describe) }));
        return;
      }
      if (ids.length === 0) {
        setError(t("noChatModels"));
        return;
      }
      const model =
        connection.default_model && ids.includes(connection.default_model)
          ? connection.default_model
          : recommendModel(ids, preset.models);
      if (model !== connection.default_model) {
        connection = await api<Connection>(`/tenant/connections/${connection.id}`, {
          method: "PATCH",
          json: { default_model: model },
        });
      }
      setConnected({ provider: preset.label ?? preset.name, model });
    } catch (e) {
      setError(describe(e));
    } finally {
      setBusy(false);
    }
  }

  const skipConfirm = {
    title: t("skipTitle"),
    description: t("skipDescription"),
    confirmLabel: t("skipConfirm"),
    cancelLabel: t("skipCancel"),
  };

  if (ready || connected) {
    return (
      <StepFrame step="model" nav={nav} onSubmit={() => void nav.next()}>
        <Callout tone="brand" icon={<CheckCircle2Icon aria-hidden />} data-testid="setup-model-ready">
          <span className="flex-1">
            {connected ? t("connected", connected) : t("ready")}{" "}
            <LeaveLink to="/settings#connections" leave={nav.leave}>
              {t("manage")}
            </LeaveLink>
          </span>
        </Callout>
      </StepFrame>
    );
  }

  return (
    <StepFrame
      step="model"
      nav={nav}
      onSubmit={() => void connect()}
      submitLabel={mode === "key" ? t("connect") : undefined}
      busy={busy || (mode === "key" && !preset)}
      error={error}
      skipConfirm={skipConfirm}
      extra={
        mode === "invite" && (
          <JoinPanel
            onJoined={() => {
              void nav.next();
            }}
          />
        )
      }
    >
      <Segmented
        label={t("modeLabel")}
        value={mode}
        onChange={(value) => {
          setError(null);
          setMode(value);
        }}
        options={[
          { value: "key", label: t("modeKey") },
          { value: "invite", label: t("modeInvite") },
        ]}
        className="flex h-9 self-start [&>button]:h-full"
      />
      {mode === "key" && presets && (
        <>
          <div className="flex flex-col gap-2">
            <Label htmlFor="setup-provider">{t("provider")}</Label>
            <Select
              id="setup-provider"
              value={choice}
              onValueChange={setChoice}
              options={presets.map((p) => ({ value: p.name, label: p.label ?? p.name }))}
            />
            <p className="text-xs text-muted-foreground">
              {t("moreProviders")}{" "}
              <LeaveLink to="/settings#connections" leave={nav.leave}>
                {t("settingsLink")}
              </LeaveLink>
            </p>
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="setup-api-key">{t("apiKey")}</Label>
            <Input
              id="setup-api-key"
              type="password"
              autoComplete="off"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
            />
            <p className="text-xs text-muted-foreground">{t("apiKeyHint")}</p>
          </div>
        </>
      )}
      {mode === "invite" && <p className="text-sm text-muted-foreground">{t("inviteHint")}</p>}
    </StepFrame>
  );
}
