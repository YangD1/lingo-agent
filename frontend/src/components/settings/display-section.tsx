"use client";

import { useTranslations } from "next-intl";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useShowActivity } from "@/lib/preferences";

/** Per-browser display preferences (ADR 0013 §3: hiding changes display only). */
export function DisplaySection() {
  const t = useTranslations("settings.display");
  const [showActivity, setShowActivity] = useShowActivity();
  return (
    <Card id="display">
      <CardHeader>
        <CardTitle>{t("title")}</CardTitle>
        <CardDescription>{t("description")}</CardDescription>
      </CardHeader>
      <CardContent>
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
