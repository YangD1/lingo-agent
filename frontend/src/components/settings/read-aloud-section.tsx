"use client";

import { useTranslations } from "next-intl";

import { SpeechSettings } from "@/components/speech/speech-settings";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

/** Read-aloud voices and speed for this browser (ADR 0018 §2). */
export function ReadAloudSection() {
  const t = useTranslations("speech");
  return (
    <Card id="read-aloud">
      <CardHeader>
        <CardTitle>{t("title")}</CardTitle>
        <CardDescription>{t("description")}</CardDescription>
      </CardHeader>
      <CardContent>
        <SpeechSettings />
      </CardContent>
    </Card>
  );
}
