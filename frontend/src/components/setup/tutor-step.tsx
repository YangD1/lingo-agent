"use client";

import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import { useDescribeError } from "@/components/settings/use-describe-error";
import { DEFAULT_FUR } from "@/components/tutor/avatar-draw";
import { FurPicker, OutfitPicker } from "@/components/tutor/looks-fields";
import { TutorAvatar } from "@/components/tutor/tutor-avatar";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api } from "@/lib/api";
import {
  DEFAULT_TUTOR,
  type Tutor,
  type TutorForm,
  type TutorOptions,
  formChanged,
  loadTutor,
  setTutor,
  toBody,
  toForm,
} from "@/lib/tutor";

import { type StepNav, StepFrame } from "./step-frame";

/**
 * Step 4: the assistant's name and looks (ADR 0042 §2). Models, voices and the pet's
 * switches stay on "My assistant"; saving here keeps them as they are.
 */
export function TutorStep({ nav }: { nav: StepNav }) {
  const t = useTranslations("setup.steps.tutor");
  const tLooks = useTranslations("tutor.looks");
  const describe = useDescribeError();
  const [saved, setSaved] = useState<Tutor | null>(null);
  const [options, setOptions] = useState<TutorOptions | null>(null);
  const [form, setForm] = useState<TutorForm | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([loadTutor(), api<TutorOptions>("/tutor/options")]).then(
      ([tutor, opts]) => {
        setSaved(tutor);
        setOptions(opts);
        setForm(toForm(tutor, opts));
      },
      (e: unknown) => setError(describe(e)),
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps -- load once
  }, []);

  async function save() {
    if (!saved || !options || !form) return;
    setBusy(true);
    setError(null);
    try {
      if (formChanged(saved, form, options)) {
        const tutor = await api<Tutor>("/tutor", { method: "PUT", json: toBody(form, options) });
        setSaved(tutor);
        setTutor(tutor);
      }
      await nav.next();
    } catch (e) {
      setError(describe(e));
    } finally {
      setBusy(false);
    }
  }

  const change = (patch: Partial<TutorForm>) => setForm((f) => f && { ...f, ...patch });
  const name = form?.name.trim() || DEFAULT_TUTOR.display_name;
  const fur = form?.color || DEFAULT_FUR;

  return (
    <StepFrame step="tutor" nav={nav} onSubmit={save} busy={busy || !form} error={error}>
      {form && (
        <>
          <div className="flex items-center gap-4">
            <TutorAvatar
              outfit={form.avatar}
              fur={fur}
              animate={form.animate}
              state="idle"
              size={96}
              label={tLooks("preview", { name })}
            />
            <div className="flex min-w-0 flex-1 flex-col gap-2">
              <Label htmlFor="setup-tutor-name">{tLooks("name")}</Label>
              <Input
                id="setup-tutor-name"
                value={form.name}
                placeholder={DEFAULT_TUTOR.display_name}
                maxLength={40}
                onChange={(e) => change({ name: e.target.value })}
              />
              <p className="text-xs text-muted-foreground">{t("nameHint")}</p>
            </div>
          </div>
          <OutfitPicker value={form.avatar} fur={fur} onChange={(avatar) => change({ avatar })} />
          <FurPicker value={form.color} onChange={(color) => change({ color })} />
        </>
      )}
    </StepFrame>
  );
}
