"use client";

import { Target } from "lucide-react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";

import { Callout } from "@/components/ui/callout";
import { CefrTag, Tag, isCefrLevel } from "@/components/ui/tag";
import { kcName, learnerHref } from "@/lib/learner";
import type { Conversation } from "@/lib/types";

/** Says which grammar point a practice conversation is about, with its evidence a click away. */
export function PracticeBar({ kc }: { kc: NonNullable<Conversation["focus_kc"]> }) {
  const t = useTranslations("chat.practice");
  const locale = useLocale();
  return (
    <Callout
      tone="neutral"
      icon={<Target aria-hidden />}
      className="mx-auto mt-3 w-[calc(100%-1.5rem)] max-w-3xl"
      data-testid="practice-bar"
      action={
        <Link
          href={learnerHref(kc.id)}
          className="shrink-0 text-[13px] font-medium text-primary underline-offset-2 hover:underline"
        >
          {t("evidence")}
        </Link>
      }
    >
      {t("label", { kc: kcName(kc, locale) })}{" "}
      {isCefrLevel(kc.cefr) ? <CefrTag level={kc.cefr} /> : <Tag>{kc.cefr}</Tag>}
    </Callout>
  );
}
