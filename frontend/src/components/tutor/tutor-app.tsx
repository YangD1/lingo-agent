"use client";

import { RotateCcwIcon, SquareIcon, Volume2Icon } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import { AiBadge } from "@/components/ai-badge";
import { useDescribeError } from "@/components/settings/use-describe-error";
import { Button } from "@/components/ui/button";
import { Callout } from "@/components/ui/callout";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { ErrorText } from "@/components/ui/error-text";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { api } from "@/lib/api";
import { useHashFlash } from "@/lib/hash-flash";
import { stopSpeaking, tryServerVoice, useSpeaking } from "@/lib/speech";
import {
  DEFAULT_TUTOR,
  type Tutor,
  type TutorChain,
  type TutorForm,
  type TutorOptions,
  formChanged,
  loadTutor,
  setTutor,
  splitRef,
  toBody,
  toForm,
  voiceSample,
  voicesFor,
} from "@/lib/tutor";
import { VOICE_LANGUAGES, type VoiceLanguage, type VoiceOption } from "@/lib/types";

import { DEFAULT_FUR } from "./avatar-draw";
import { FurPicker, OutfitPicker } from "./looks-fields";
import { TutorAvatar } from "./tutor-avatar";

// Whose reading a tried voice is, so the preview speaks only for it.
const TRY_OWNER = "tutor-voice-try";

/**
 * "My tutor" (ADR 0032): the learner's own tutor's looks, name, and the model and voices
 * that talk to them. Changes show in the preview at once and apply when saved.
 */
export function TutorApp() {
  const t = useTranslations("tutor");
  const tNav = useTranslations("nav");
  const describe = useDescribeError();
  const [saved, setSaved] = useState<Tutor | null>(null);
  const [options, setOptions] = useState<TutorOptions | null>(null);
  const [form, setForm] = useState<TutorForm | null>(null);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    Promise.all([loadTutor(), api<TutorOptions>("/tutor/options")]).then(
      ([tutor, opts]) => {
        setSaved(tutor);
        setOptions(opts);
        setForm(toForm(tutor, opts));
      },
      (e: unknown) => setMessage({ ok: false, text: describe(e) }),
    );
    return () => stopSpeaking();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- load once
  }, []);
  useHashFlash();
  const loaded = form !== null;
  useEffect(() => {
    // Came from a name under a reply: ready to rename (the flash does the scrolling).
    if (loaded && window.location.hash === "#looks") {
      document.getElementById("tutor-name")?.focus({ preventScroll: true });
    }
  }, [loaded]);

  const header = (
    <h1 className="text-[26px] font-bold tracking-tight max-md:sr-only">
      {saved ? t("heading", { name: saved.display_name }) : tNav("tutor")}
    </h1>
  );
  if (!saved || !options || !form) {
    return (
      <Page>
        {header}
        {message && <ErrorText>{message.text}</ErrorText>}
      </Page>
    );
  }

  const change = (patch: Partial<TutorForm>) => {
    setMessage(null);
    setForm((f) => f && { ...f, ...patch });
  };
  const dirty = formChanged(saved, form, options);
  const name = form.name.trim() || DEFAULT_TUTOR.display_name;

  function show(tutor: Tutor, opts: TutorOptions) {
    setSaved(tutor);
    setForm(toForm(tutor, opts));
    setTutor(tutor);
  }

  async function save() {
    if (!form || !options) return;
    setSaving(true);
    setMessage(null);
    try {
      const tutor = await api<Tutor>("/tutor", { method: "PUT", json: toBody(form, options) });
      show(tutor, options);
      setMessage({ ok: true, text: t("saved") });
    } catch (e) {
      setMessage({ ok: false, text: describe(e) });
    } finally {
      setSaving(false);
    }
  }

  async function reset() {
    if (!options) return;
    setSaving(true);
    setMessage(null);
    try {
      await api("/tutor", { method: "DELETE" });
      show(DEFAULT_TUTOR, options);
      setMessage({ ok: true, text: t("resetDone") });
    } catch (e) {
      setMessage({ ok: false, text: describe(e) });
    } finally {
      setSaving(false);
    }
  }

  return (
    <Page>
      {header}
      <p className="text-sm text-muted-foreground">{t("intro")}</p>
      <LooksCard form={form} name={name} onChange={change} />
      <ChatCard
        chain={options.chat}
        value={form.chat_model}
        dropped={saved.unavailable.includes("chat_model")}
        onChange={(chat_model) => change({ chat_model })}
      />
      <VoicesCard
        options={options.read_aloud}
        voices={form.voices}
        name={name}
        dropped={saved.unavailable.includes("voices")}
        onChange={(voices) => change({ voices })}
      />
      <CallCard
        options={options.realtime}
        model={form.realtime_model}
        voice={form.realtime_voice}
        dropped={saved.unavailable.includes("realtime_model")}
        onChange={(realtime_model, realtime_voice) => change({ realtime_model, realtime_voice })}
      />
      <div className="sticky bottom-0 -mx-4 flex flex-wrap items-center gap-3 border-t bg-background/95 px-4 py-3 backdrop-blur md:static md:mx-0 md:border-0 md:bg-transparent md:px-0 md:py-0">
        <Button onClick={() => void save()} disabled={!dirty || saving} data-testid="tutor-save">
          {t("save")}
        </Button>
        <ConfirmDialog
          trigger={
            <Button variant="outline" disabled={saving} data-testid="tutor-reset">
              <RotateCcwIcon aria-hidden />
              {t("reset")}
            </Button>
          }
          title={t("resetTitle")}
          description={t("resetDescription")}
          confirmLabel={t("reset")}
          onConfirm={() => void reset()}
        />
        {message &&
          (message.ok ? (
            <span role="status" className="text-sm text-muted-foreground">
              {message.text}
            </span>
          ) : (
            <ErrorText>{message.text}</ErrorText>
          ))}
      </div>
    </Page>
  );
}

function Page({ children }: { children: React.ReactNode }) {
  return (
    <div className="pet-safe flex-1 overflow-y-auto">
      <div className="mx-auto flex max-w-3xl flex-col gap-3.5 p-4 md:gap-4 md:px-10 md:py-8">
        {children}
      </div>
    </div>
  );
}

function LooksCard({
  form,
  name,
  onChange,
}: {
  form: TutorForm;
  name: string;
  onChange: (patch: Partial<TutorForm>) => void;
}) {
  const t = useTranslations("tutor.looks");
  const speaking = useSpeaking(TRY_OWNER);
  const fur = form.color || DEFAULT_FUR;
  return (
    // `/tutor#looks`: the name under each reply leads here (ADR 0040 §3).
    <Card id="looks" data-testid="tutor-looks" className="scroll-mt-14 lg:scroll-mt-4">
      <CardHeader>
        <CardTitle>{t("title")}</CardTitle>
        <CardDescription>{t("description")}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-5 sm:flex-row sm:items-start">
        <div className="flex shrink-0 flex-col items-center gap-1 self-center sm:self-start">
          <TutorAvatar
            outfit={form.avatar}
            fur={fur}
            animate={form.animate}
            state={speaking ? "speaking" : "idle"}
            size={160}
            label={t("preview", { name })}
          />
          <span className="text-sm font-medium" data-testid="tutor-preview-name">
            {name}
          </span>
        </div>
        <div className="flex min-w-0 flex-1 flex-col gap-4">
          <div className="flex flex-col gap-2">
            <Label htmlFor="tutor-name">{t("name")}</Label>
            <Input
              id="tutor-name"
              value={form.name}
              placeholder={DEFAULT_TUTOR.display_name}
              maxLength={40}
              onChange={(e) => onChange({ name: e.target.value })}
            />
            <p className="text-xs text-muted-foreground">{t("nameHint")}</p>
          </div>
          <OutfitPicker
            value={form.avatar}
            fur={fur}
            onChange={(avatar) => onChange({ avatar })}
          />
          <FurPicker value={form.color} onChange={(color) => onChange({ color })} />
          <SwitchRow
            id="tutor-pet"
            label={t("pet")}
            hint={t("petHint")}
            checked={form.pet}
            onChange={(pet) => onChange({ pet })}
          />
          {form.pet && (
            <SwitchRow
              id="tutor-nudges"
              label={t("nudges")}
              hint={t("nudgesHint")}
              checked={form.nudges}
              onChange={(nudges) => onChange({ nudges })}
            />
          )}
          {form.pet && (
            <SwitchRow
              id="tutor-daily-opening"
              label={t("dailyOpening")}
              badge={<AiBadge feature="pet_daily_opening" />}
              hint={t("dailyOpeningHint")}
              checked={form.daily_opening}
              onChange={(daily_opening) => onChange({ daily_opening })}
            />
          )}
          <SwitchRow
            id="tutor-workspace-auto"
            label={t("workspaceAutoOpen")}
            hint={t("workspaceAutoOpenHint")}
            checked={form.workspace_auto_open}
            onChange={(workspace_auto_open) => onChange({ workspace_auto_open })}
          />
          <SwitchRow
            id="tutor-animate"
            label={t("animate")}
            hint={t("animateHint")}
            checked={form.animate}
            onChange={(animate) => onChange({ animate })}
          />
        </div>
      </CardContent>
    </Card>
  );
}

function SwitchRow({
  id,
  label,
  hint,
  badge,
  checked,
  onChange,
}: {
  id: string;
  label: string;
  hint: string;
  /** An AI badge by the label, outside it: pressing it must not flip the switch. */
  badge?: React.ReactNode;
  checked: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <div className="flex items-center justify-between gap-4">
      <div className="flex items-start gap-1.5">
        <label htmlFor={id} className="flex flex-col gap-1">
          <span className="text-sm font-medium">{label}</span>
          <span className="text-xs text-muted-foreground">{hint}</span>
        </label>
        {badge}
      </div>
      <Switch id={id} checked={checked} onCheckedChange={(on) => onChange(on)} />
    </div>
  );
}

/** "model · connection". */
function modelLabel(ref: string): string {
  const { connection, model } = splitRef(ref);
  return connection ? `${model} · ${connection}` : model;
}

/** Who pays, and whether a member's share is used up (ADR 0031 §5). */
function ChainNotes({ chain }: { chain: TutorChain }) {
  const t = useTranslations("tutor");
  return (
    <>
      {chain.provided_by && (
        <p className="text-xs text-muted-foreground" data-testid="tutor-provided-by">
          {t("providedBy", { name: chain.provided_by })}
        </p>
      )}
      {chain.quota_exhausted && <Callout tone="warning">{t("quotaExhausted")}</Callout>}
    </>
  );
}

/** A saved choice whose model can't be used any more: what is used instead (ADR 0032 §3). */
function Dropped({ now }: { now: string | undefined }) {
  const t = useTranslations("tutor");
  return (
    <Callout tone="warning" data-testid="tutor-dropped">
      {now ? t("dropped", { model: modelLabel(now) }) : t("droppedNone")}
    </Callout>
  );
}

function ChatCard({
  chain,
  value,
  dropped,
  onChange,
}: {
  chain: TutorChain;
  value: string;
  dropped: boolean;
  onChange: (value: string) => void;
}) {
  const t = useTranslations("tutor.chat");
  const tTutor = useTranslations("tutor");
  return (
    <Card data-testid="tutor-chat">
      <CardHeader>
        <CardTitle className="flex items-center gap-1.5">
          {t("title")}
          <AiBadge feature="chat_message" />
        </CardTitle>
        <CardDescription>{t("description")}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {dropped && <Dropped now={chain.models[0]} />}
        {chain.models.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            {t("none")} <SettingsLink />
          </p>
        ) : (
          <>
            <Label htmlFor="tutor-chat-model">{t("model")}</Label>
            <Select
              id="tutor-chat-model"
              value={value}
              onValueChange={onChange}
              options={[
                {
                  value: "",
                  label: tTutor("followSettings", { current: modelLabel(chain.models[0]) }),
                },
                ...chain.models.map((ref) => ({ value: ref, label: modelLabel(ref) })),
              ]}
            />
            <p className="text-xs text-muted-foreground">{t("hint")}</p>
          </>
        )}
        <ChainNotes chain={chain} />
      </CardContent>
    </Card>
  );
}

function SettingsLink({ hash = "" }: { hash?: string }) {
  const t = useTranslations("tutor");
  return (
    <Link href={`/settings${hash}`} className="text-primary underline-offset-4 hover:underline">
      {t("toSettings")}
    </Link>
  );
}

/** "name · gender · accent · note", leaving out what the vendor doesn't say. */
function useVoiceLabel(): (option: VoiceOption) => string {
  const t = useTranslations("tutor.voices");
  return (option) => {
    const gender = option.gender ? ` · ${t(`gender.${option.gender}`)}` : "";
    const accent =
      option.accent && (VOICE_LANGUAGES as readonly string[]).includes(option.accent)
        ? ` · ${t(`lang.${option.accent as VoiceLanguage}`)}`
        : "";
    return `${option.name}${gender}${accent}${option.note ? ` · ${option.note}` : ""}`;
  };
}

function VoicesCard({
  options,
  voices,
  name,
  dropped,
  onChange,
}: {
  options: TutorOptions["read_aloud"];
  voices: Record<VoiceLanguage, string>;
  name: string;
  dropped: boolean;
  onChange: (voices: Record<VoiceLanguage, string>) => void;
}) {
  const t = useTranslations("tutor.voices");
  const tTutor = useTranslations("tutor");
  const describe = useDescribeError();
  const speaking = useSpeaking(TRY_OWNER);
  const voiceLabel = useVoiceLabel();
  const [trying, setTrying] = useState<VoiceLanguage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const model = options.voice_model;

  function tryVoice(lang: VoiceLanguage, voice: string) {
    if (speaking && trying === lang) return stopSpeaking();
    setTrying(lang);
    setError(null);
    tryServerVoice(TRY_OWNER, voiceSample(lang, name), lang, voice).catch((e: unknown) =>
      setError(describe(e)),
    );
  }

  return (
    <Card data-testid="tutor-voices">
      <CardHeader>
        <CardTitle className="flex items-center gap-1.5">
          {t("title")}
          {model && <AiBadge feature="read_aloud" />}
        </CardTitle>
        <CardDescription>{t("description")}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {dropped && <Dropped now={model ?? undefined} />}
        {!model ? (
          <p className="text-sm text-muted-foreground">
            {t("none")} <SettingsLink hash="#read-aloud" />
          </p>
        ) : (
          <>
            <p className="text-xs text-muted-foreground">
              {t("model", { model: modelLabel(model) })}
            </p>
            {VOICE_LANGUAGES.map((lang) => {
              const offered = voicesFor(options.voice_options, lang);
              const builtIn = options.default_voices[lang] ?? null;
              const voice = voices[lang] || builtIn;
              const id = `tutor-voice-${lang}`;
              const set = (value: string) => onChange({ ...voices, [lang]: value });
              const followLabel = builtIn
                ? tTutor("followSettings", { current: builtIn })
                : t("noVoice");
              return (
                <div key={lang} className="flex flex-col gap-1.5">
                  <Label htmlFor={id}>{t(`lang.${lang}`)}</Label>
                  <div className="flex gap-2">
                    {options.voice_options.length > 0 ? (
                      <Select
                        id={id}
                        value={voices[lang]}
                        onValueChange={set}
                        className="min-w-0 flex-1"
                        options={[
                          { value: "", label: followLabel },
                          ...offered.map((o) => ({ value: o.id, label: voiceLabel(o) })),
                        ]}
                      />
                    ) : (
                      <Input
                        id={id}
                        value={voices[lang]}
                        placeholder={followLabel}
                        maxLength={200}
                        autoComplete="off"
                        spellCheck={false}
                        onChange={(e) => set(e.target.value)}
                        className="min-w-0 flex-1 font-mono text-xs"
                      />
                    )}
                    <Button
                      type="button"
                      variant="outline"
                      disabled={!voice}
                      onClick={() => voice && tryVoice(lang, voice)}
                      data-testid={`tutor-try-${lang}`}
                    >
                      {speaking && trying === lang ? (
                        <SquareIcon aria-hidden />
                      ) : (
                        <Volume2Icon aria-hidden />
                      )}
                      {speaking && trying === lang ? t("stop") : t("try")}
                    </Button>
                  </div>
                </div>
              );
            })}
            {options.voice_options.length === 0 && (
              <p className="text-xs text-muted-foreground">{t("typed")}</p>
            )}
            <p className="text-xs text-muted-foreground">{t("hint")}</p>
            {error && <ErrorText>{error}</ErrorText>}
          </>
        )}
        <ChainNotes chain={options} />
      </CardContent>
    </Card>
  );
}

function CallCard({
  options,
  model,
  voice,
  dropped,
  onChange,
}: {
  options: TutorOptions["realtime"];
  model: string;
  voice: string;
  dropped: boolean;
  onChange: (model: string, voice: string) => void;
}) {
  const t = useTranslations("tutor.call");
  const tTutor = useTranslations("tutor");
  const voiceLabel = useVoiceLabel();
  if (options.models.length === 0 && !dropped) return null;
  const used = model || options.models[0];
  const offered = used ? (options.voice_options[used] ?? []) : [];
  const builtIn = used ? (options.default_voices[used] ?? null) : null;
  return (
    <Card data-testid="tutor-call">
      <CardHeader>
        <CardTitle className="flex items-center gap-1.5">
          {t("title")}
          <AiBadge feature="realtime_call" />
        </CardTitle>
        <CardDescription>{t("description")}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {dropped && <Dropped now={options.models[0]} />}
        {options.models.length > 0 && (
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="tutor-call-model">{t("model")}</Label>
              <Select
                id="tutor-call-model"
                value={model}
                // Voices are the model's own: another model starts from its default.
                onValueChange={(next) => onChange(next, "")}
                options={[
                  {
                    value: "",
                    label: tTutor("followSettings", { current: modelLabel(options.models[0]) }),
                  },
                  ...options.models.map((ref) => ({ value: ref, label: modelLabel(ref) })),
                ]}
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="tutor-call-voice">{t("voice")}</Label>
              {offered.length > 0 ? (
                <Select
                  id="tutor-call-voice"
                  value={voice}
                  // A voice belongs to a model: following the settings page pins the one in use.
                  onValueChange={(next) => onChange(model || used, next)}
                  options={[
                    {
                      value: "",
                      label: builtIn
                        ? tTutor("followSettings", { current: builtIn })
                        : t("vendorDefault"),
                    },
                    ...offered.map((o) => ({ value: o.id, label: voiceLabel(o) })),
                  ]}
                />
              ) : (
                <p className="text-sm text-muted-foreground">{t("noVoices")}</p>
              )}
            </div>
          </div>
        )}
        <ChainNotes chain={options} />
      </CardContent>
    </Card>
  );
}
