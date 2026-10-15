"use client";

import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import { useDescribeError } from "@/components/settings/use-describe-error";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Segmented } from "@/components/ui/segmented";
import { Select } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api";
import { type ProfileForm, profileChanges, toForm } from "@/lib/profile";
import { EXAMS, type Profile } from "@/lib/types";

import { type StepNav, StepFrame } from "./step-frame";

// Quick picks for minutes a day; any other number is kept and editable in "About me".
const MINUTES = ["10", "20", "30", "60"] as const;

/**
 * Step 3: why and how much the learner studies (ADR 0042 §2). Only changed fields are sent:
 * the backend marks those as set by hand, and reflection then leaves them alone (ADR 0009).
 */
export function GoalsStep({ nav }: { nav: StepNav }) {
  const t = useTranslations("setup.steps.goals");
  const tProfile = useTranslations("memory.profile");
  const describe = useDescribeError();
  const [saved, setSaved] = useState<Profile | null>(null);
  const [form, setForm] = useState<ProfileForm | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<Profile>("/profile").then(
      (profile) => {
        setSaved(profile);
        setForm(toForm(profile));
      },
      (e: unknown) => setError(describe(e)),
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps -- load once
  }, []);

  const set = (patch: Partial<ProfileForm>) => setForm((f) => f && { ...f, ...patch });

  async function save() {
    if (!saved || !form) return;
    setBusy(true);
    setError(null);
    try {
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
    <StepFrame step="goals" nav={nav} onSubmit={save} busy={busy || !form} error={error}>
      {form && (
        <>
          <div className="flex flex-col gap-2">
            <Label htmlFor="setup-goal">{tProfile("fields.goal")}</Label>
            <Textarea
              id="setup-goal"
              value={form.goal}
              onChange={(e) => set({ goal: e.target.value })}
              placeholder={t("goalPlaceholder")}
              maxLength={1000}
            />
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="setup-exam">{tProfile("fields.target_exam")}</Label>
            <Select
              id="setup-exam"
              value={form.target_exam}
              onValueChange={(target_exam) => set({ target_exam })}
              options={[
                { value: "", label: t("noExam") },
                ...EXAMS.map((exam) => ({ value: exam, label: tProfile(`exams.${exam}`) })),
              ]}
            />
          </div>
          <div className="flex flex-col gap-2">
            <span className="text-sm leading-none font-medium">{tProfile("fields.daily_minutes")}</span>
            <Segmented
              label={tProfile("fields.daily_minutes")}
              value={form.daily_minutes}
              onChange={(daily_minutes) => set({ daily_minutes })}
              options={[
                ...MINUTES.map((m) => ({ value: m, label: t("minutes", { n: Number(m) }) })),
                // A number set elsewhere stays selectable as it is.
                ...(form.daily_minutes && !(MINUTES as readonly string[]).includes(form.daily_minutes)
                  ? [{ value: form.daily_minutes, label: t("minutes", { n: Number(form.daily_minutes) }) }]
                  : []),
              ]}
              className="flex h-9 self-start [&>button]:h-full"
            />
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="setup-interests">{tProfile("fields.interests")}</Label>
            <Input
              id="setup-interests"
              value={form.interests}
              onChange={(e) => set({ interests: e.target.value })}
              placeholder={tProfile("interestsHint")}
            />
            <p className="text-xs text-muted-foreground">{t("interestsHint")}</p>
          </div>
        </>
      )}
    </StepFrame>
  );
}
