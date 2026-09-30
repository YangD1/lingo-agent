"use client";

import { Target } from "lucide-react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";

import { kcName, learnerHref } from "@/lib/learner";
import type { Conversation } from "@/lib/types";

/** Says which grammar point a practice conversation is about, with its evidence a click away. */
export function PracticeBar({ kc }: { kc: NonNullable<Conversation["focus_kc"]> }) {
  const t = useTranslations("chat.practice");
  const locale = useLocale();
  return (
    <div
      className="mx-auto mt-3 flex w-full max-w-3xl items-center gap-2 rounded-lg border px-4 py-2 text-sm"
      data-testid="practice-bar"
    >
      <Target className="size-4 shrink-0 text-muted-foreground" aria-hidden />
      <span className="flex-1">
        {t("label", { kc: kcName(kc, locale) })}{" "}
        <span className="text-xs text-muted-foreground">{kc.cefr}</span>
      </span>
      <Link href={learnerHref(kc.id)} className="underline-offset-2 hover:underline">
        {t("evidence")}
      </Link>
    </div>
  );
}
