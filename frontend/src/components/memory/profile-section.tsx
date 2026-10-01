"use client";

import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import { useDescribeError } from "@/components/settings/use-describe-error";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { NativeSelect } from "@/components/ui/native-select";
import { Textarea } from "@/components/ui/textarea";
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
      <p role="alert" className="text-sm text-destructive">
        {message.text}
      </p>
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

  const browserZone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  const field = (name: ProfileField, control: React.ReactNode) => (
    <div className="flex flex-col gap-1.5">
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
          <p className="text-sm" data-testid="profile-cefr">
            {t("cefr")}{" "}
            <span className="font-medium">{saved.cefr_level ?? t("cefrUnknown")}</span>
          </p>
          <div className="grid gap-4 sm:grid-cols-2">
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
            {field(
              "chat_language",
              <NativeSelect
                id="profile-chat_language"
                value={form.chat_language}
                onChange={set("chat_language")}
              >
                <option value="">
                  {t("chatLanguageAuto", {
                    current: t(`chatLanguages.${saved.chat_language_effective}`),
                  })}
                </option>
                <option value="zh">{t("chatLanguages.zh")}</option>
                <option value="en">{t("chatLanguages.en")}</option>
              </NativeSelect>,
            )}
            {field(
              "daily_minutes",
              <Input
                id="profile-daily_minutes"
                type="number"
                inputMode="numeric"
                min={1}
                max={600}
                value={form.daily_minutes}
                onChange={set("daily_minutes")}
              />,
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
                    size="sm"
                    variant="outline"
                    className="h-8"
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
          <p className="text-xs text-muted-foreground">{t("manualHint")}</p>
          <div className="flex items-center gap-3">
            <Button type="submit" size="sm" disabled={!dirty || saving}>
              {t("save")}
            </Button>
            {dirty && (
              <Button
                type="button"
                size="sm"
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
