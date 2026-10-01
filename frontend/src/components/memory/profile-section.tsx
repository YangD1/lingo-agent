"use client";

import { Info, Minus, Plus } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import { useDescribeError } from "@/components/settings/use-describe-error";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { NativeSelect } from "@/components/ui/native-select";
import { Segmented } from "@/components/ui/segmented";
import { CefrTag, isCefrLevel } from "@/components/ui/tag";
import { Textarea } from "@/components/ui/textarea";
import { ErrorText } from "@/components/ui/error-text";
import { api } from "@/lib/api";
import { type ProfileField, type ProfileForm, profileChanges, toForm } from "@/lib/profile";
import { EXAMS, type Profile } from "@/lib/types";

export function ProfileSection() {
  const t = useTranslations("memory.profile");
  const describe = useDescribeError();
  const [saved, setSaved] = useState<Profile | null>(null);
  const [form, setForm] = useState<ProfileForm | null>(null);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [saving, setSaving] = useState(false);

  function show(profile: Profile) {
    setSaved(profile);
    setForm(toForm(profile));
  }

  useEffect(() => {
    api<Profile>("/profile").then(show, (e: unknown) =>
      setMessage({ ok: false, text: describe(e) }),
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps -- load once
  }, []);

  if (!saved || !form) {
    return message ? (
      <ErrorText>{message.text}</ErrorText>
    ) : null;
  }

  const changes = profileChanges(saved, form);
  const dirty = Object.keys(changes).length > 0;
  const set = (field: ProfileField) => (e: { target: { value: string } }) => {
    setMessage(null);
    setForm((f) => f && { ...f, [field]: e.target.value });
  };

  async function save() {
    setSaving(true);
    setMessage(null);
    try {
      show(await api<Profile>("/profile", { method: "PATCH", json: changes }));
      setMessage({ ok: true, text: t("saved") });
    } catch (e) {
      setMessage({ ok: false, text: describe(e) });
    } finally {
      setSaving(false);
    }
  }

  // The stepper moves by five minutes, within what the backend accepts.
  const stepMinutes = (delta: number) => {
    const current = Number.parseInt(form.daily_minutes, 10) || 0;
    const next = Math.min(600, Math.max(1, current + delta));
    set("daily_minutes")({ target: { value: String(next) } });
  };

  const browserZone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  const field = (name: ProfileField, control: React.ReactNode) => (
    <div className="flex flex-col gap-2">
      <Label htmlFor={`profile-${name}`}>{t(`fields.${name}`)}</Label>
      {control}
    </div>
  );

  return (
    <Card data-testid="profile">
      <CardHeader>
        <CardTitle>{t("title")}</CardTitle>
        <CardDescription>{t("description")}</CardDescription>
      </CardHeader>
      <CardContent>
        <form
          className="flex flex-col gap-4"
          onSubmit={(e) => {
            e.preventDefault();
            void save();
          }}
        >
          <p className="flex items-center gap-2 text-sm" data-testid="profile-cefr">
            {t("cefr")}
            {saved.cefr_level && isCefrLevel(saved.cefr_level) ? (
              <CefrTag level={saved.cefr_level} />
            ) : (
              <span className="text-muted-foreground">{t("cefrUnknown")}</span>
            )}
          </p>
          <div className="grid gap-x-6 gap-y-4 sm:grid-cols-2">
            {field(
              "native_language",
              <Input
                id="profile-native_language"
                value={form.native_language}
                onChange={set("native_language")}
                maxLength={50}
              />,
            )}
            {field(
              "occupation",
              <Input
                id="profile-occupation"
                value={form.occupation}
                onChange={set("occupation")}
                maxLength={200}
              />,
            )}
            {field(
              "target_exam",
              <NativeSelect
                id="profile-target_exam"
                value={form.target_exam}
                onChange={set("target_exam")}
              >
                <option value="">{t("notSet")}</option>
                {EXAMS.map((exam) => (
                  <option key={exam} value={exam}>
                    {t(`exams.${exam}`)}
                  </option>
                ))}
              </NativeSelect>,
            )}
            {field(
              "explanation_language",
              <NativeSelect
                id="profile-explanation_language"
                value={form.explanation_language}
                onChange={set("explanation_language")}
              >
                <option value="">{t("notSet")}</option>
                <option value="zh">{t("languages.zh")}</option>
                <option value="en">{t("languages.en")}</option>
              </NativeSelect>,
            )}
            <div className="flex flex-col gap-2">
              <span id="profile-chat_language" className="text-sm leading-none font-medium">
                {t("fields.chat_language")}
              </span>
              <Segmented
                label={t("fields.chat_language")}
                value={form.chat_language}
                onChange={(value) => set("chat_language")({ target: { value } })}
                options={[
                  { value: "", label: t("chatLanguageByLevel") },
                  { value: "zh", label: t("chatLanguages.zh") },
                  { value: "en", label: t("chatLanguages.en") },
                ]}
                className="flex h-9 [&>button]:h-full"
              />
              {form.chat_language === "" && (
                <p className="text-xs text-muted-foreground">
                  {t("chatLanguageNow", {
                    current: t(`chatLanguages.${saved.chat_language_effective}`),
                  })}
                </p>
              )}
            </div>
            {field(
              "daily_minutes",
              <div className="flex h-10 items-stretch overflow-hidden rounded-md border border-input bg-card md:h-9">
                <button
                  type="button"
                  aria-label={t("fewerMinutes")}
                  onClick={() => stepMinutes(-5)}
                  className="flex w-9 items-center justify-center text-muted-foreground outline-none hover:bg-accent hover:text-foreground focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-ring [&_svg]:size-4"
                >
                  <Minus />
                </button>
                <input
                  id="profile-daily_minutes"
                  type="number"
                  inputMode="numeric"
                  min={1}
                  max={600}
                  value={form.daily_minutes}
                  onChange={set("daily_minutes")}
                  className="w-14 [appearance:textfield] border-x border-input bg-transparent text-center font-mono text-sm tabular-nums outline-none focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-ring [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none"
                />
                <button
                  type="button"
                  aria-label={t("moreMinutes")}
                  onClick={() => stepMinutes(5)}
                  className="flex w-9 items-center justify-center text-muted-foreground outline-none hover:bg-accent hover:text-foreground focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-ring [&_svg]:size-4"
                >
                  <Plus />
                </button>
              </div>,
            )}
            {field(
              "timezone",
              <div className="flex gap-2">
                <Input
                  id="profile-timezone"
                  value={form.timezone}
                  onChange={set("timezone")}
                  placeholder={browserZone}
                />
                {form.timezone !== browserZone && (
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => set("timezone")({ target: { value: browserZone } })}
                  >
                    {t("useBrowserZone")}
                  </Button>
                )}
              </div>,
            )}
          </div>
          {field(
            "interests",
            <Input
              id="profile-interests"
              value={form.interests}
              onChange={set("interests")}
              placeholder={t("interestsHint")}
            />,
          )}
          {field(
            "goal",
            <Textarea
              id="profile-goal"
              value={form.goal}
              onChange={set("goal")}
              maxLength={1000}
            />,
          )}
          <p className="flex items-start gap-2.5 rounded-lg border bg-muted px-3.5 py-2.5 text-[13px] text-muted-foreground">
            <Info aria-hidden className="mt-0.5 size-4 shrink-0" />
            {t("manualHint")}
          </p>
          <div className="flex items-center gap-3">
            <Button type="submit" disabled={!dirty || saving}>
              {t("save")}
            </Button>
            {dirty && (
              <Button
                type="button"
                variant="ghost"
                onClick={() => {
                  setMessage(null);
                  setForm(toForm(saved));
                }}
              >
                {t("discard")}
              </Button>
            )}
            {message && (
              <p
                role={message.ok ? "status" : "alert"}
                className={message.ok ? "text-sm text-muted-foreground" : "text-sm text-destructive"}
              >
                {message.text}
              </p>
            )}
          </div>
        </form>
      </CardContent>
    </Card>
  );
}
