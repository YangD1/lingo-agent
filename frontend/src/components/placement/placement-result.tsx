"use client";

import { useTranslations } from "next-intl";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { PlacementResult as Result } from "@/lib/placement";

/** The finished test: the level it gives, and what it is made of. */
export function PlacementResult({
  result,
}: {
  result: Result;
  finishedAt: string | null;
  busy: boolean;
  onRetest: () => void;
}) {
  const t = useTranslations("placement.result");
  return (
    <Card data-testid="placement-result">
      <CardHeader>
        <CardTitle>{t("title")}</CardTitle>
      </CardHeader>
      <CardContent>
        <p className="text-4xl font-semibold" data-testid="placement-level">
          {result.cefr}
        </p>
      </CardContent>
    </Card>
  );
}
