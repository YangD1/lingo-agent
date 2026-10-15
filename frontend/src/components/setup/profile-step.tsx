"use client";

import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import { useDescribeError } from "@/components/settings/use-describe-error";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Segmented } from "@/components/ui/segmented";
import { api } from "@/lib/api";
import { type ProfileForm, profileChanges, toForm } from "@/lib/profile";
import type { Profile, User } from "@/lib/types";

import { type StepNav, StepFrame } from "./step-frame";

/** Step 1: what to call the learner and which language explains things (ADR 0042 §2). */
export function ProfileStep({ user, nav }: { user: User; nav: StepNav }) {
  const t = useTranslations("setup.steps.profile");
  const tProfile = useTranslations("memory.profile");
  const describe = useDescribeError();
  const [name, setName] = useState(user.display_name ?? "");
  const [savedName, setSavedName] = useState(user.display_name ?? "");
  const [saved, setSaved] = useState<Profile | null>(null);
  const [form, setForm] = useState<ProfileForm | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<Profile>("/profile").then(
      (profile) => {
        setSaved(profile);
        // "Today" for reviews is cut in this zone: take the browser's unless one is set.
        const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
        setForm({ ...toForm(profile), timezone: profile.timezone ?? zone });
      },
      (e: unknown) => setError(describe(e)),
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps -- load once
  }, []);

  async function save() {
    if (!saved || !form) return;
    setBusy(true);
    setError(null);
    try {
      if (name.trim() !== savedName.trim()) {
        const next = await api<User>("/auth/me", { method: "PATCH", json: { display_name: name } });
        setSavedName(next.display_name ?? "");
      }
      const changes = profileChanges(saved, form);
      if (Object.keys(changes).length > 0) {
        setSaved(await api<Profile>("/profile", { method: "PATCH", json: changes }));
      }
      await nav.next();
    } catch (e) {
      setError(describe(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <StepFrame step="profile" nav={nav} onSubmit={save} busy={busy || !form} error={error}>
      <div className="flex flex-col gap-2">
        <Label htmlFor="setup-name">{t("name")}</Label>
        <Input
          id="setup-name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          maxLength={100}
          autoComplete="nickname"
          placeholder={t("namePlaceholder")}
        />
      </div>
      {form && (
        <div className="flex flex-col gap-2">
          <span className="text-sm leading-none font-medium">
            {tProfile("fields.explanation_language")}
          </span>
          <Segmented
            label={tProfile("fields.explanation_language")}
            value={form.explanation_language}
            onChange={(value) => setForm((f) => f && { ...f, explanation_language: value })}
            options={[
              { value: "zh", label: tProfile("languages.zh") },
              { value: "en", label: tProfile("languages.en") },
              { value: "", label: t("languageLater") },
            ]}
            className="flex h-9 [&>button]:h-full"
          />
          <p className="text-xs text-muted-foreground">{t("languageHint")}</p>
        </div>
      )}
    </StepFrame>
  );
}
