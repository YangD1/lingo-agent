"use client";

import { useTranslations } from "next-intl";
import { useEffect } from "react";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { ensureFontCss, FONT_CHOICES } from "@/lib/font-choice";
import { useFontChoice, useShowActivity } from "@/lib/preferences";

// The same line in every font, with IPA: the fonts differ most on Chinese and phonetics.
const FONT_SAMPLE = "Practice makes perfect. 熟能生巧";
const FONT_SAMPLE_IPA = "/ˈpræk.tɪs/";

/** Per-browser display preferences (ADR 0013 §3: hiding changes display only). */
export function DisplaySection() {
  const t = useTranslations("settings.display");
  const [showActivity, setShowActivity] = useShowActivity();
  const [font, setFont] = useFontChoice();
  // Previews need every font's stylesheet; only the sample's few pieces download.
  useEffect(() => FONT_CHOICES.forEach(ensureFontCss), []);
  return (
    <Card id="display" className="scroll-mt-14 lg:scroll-mt-4">
      <CardHeader>
        <CardTitle>{t("title")}</CardTitle>
        <CardDescription>{t("description")}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-5">
        <fieldset className="flex flex-col gap-2 text-sm">
          <legend className="mb-2 font-medium">{t("font")}</legend>
          <div className="grid gap-2 sm:grid-cols-2">
            {FONT_CHOICES.map((choice) => (
              <label
                key={choice}
                className={cn(
                  "flex cursor-pointer items-start gap-2 rounded-lg border p-3",
                  font === choice ? "border-primary bg-primary/5" : "hover:bg-muted/50",
                )}
              >
                <input
                  type="radio"
                  name="font"
                  value={choice}
                  className="mt-0.5 size-4 accent-primary"
                  checked={font === choice}
                  onChange={() => setFont(choice)}
                />
                <span className="flex min-w-0 flex-col gap-1">
                  <span>
                    {t(`fonts.${choice}.name`)}
                    <span className="block text-muted-foreground">{t(`fonts.${choice}.hint`)}</span>
                  </span>
                  <span
                    className="text-base"
                    style={{ fontFamily: `var(--font-stack-${choice})` }}
                    data-testid={`font-sample-${choice}`}
                  >
                    {FONT_SAMPLE}{" "}
                    <span className="whitespace-nowrap">{FONT_SAMPLE_IPA}</span>
                  </span>
                </span>
              </label>
            ))}
          </div>
        </fieldset>
        <label className="flex items-start gap-2 text-sm">
          <input
            type="checkbox"
            className="mt-0.5 size-4 accent-primary"
            checked={showActivity}
            onChange={(e) => setShowActivity(e.target.checked)}
          />
          <span>
            {t("showActivity")}
            <span className="block text-muted-foreground">{t("showActivityHint")}</span>
          </span>
        </label>
      </CardContent>
    </Card>
  );
}
