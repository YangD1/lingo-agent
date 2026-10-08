"use client";

import { Newspaper } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";

import { Callout } from "@/components/ui/callout";

/** Says that a reading conversation is about an article, with the way back to it (Q43h). */
export function ReadingBar({ articleId }: { articleId: number }) {
  const t = useTranslations("chat.reading");
  return (
    <Callout
      tone="neutral"
      icon={<Newspaper aria-hidden />}
      className="mx-auto mt-3 w-[calc(100%-1.5rem)] max-w-3xl"
      data-testid="reading-bar"
      action={
        <Link
          href={`/reading/${articleId}`}
          className="shrink-0 text-[13px] font-medium text-primary underline-offset-2 hover:underline"
        >
          {t("back")}
        </Link>
      }
    >
      {t("label")}
    </Callout>
  );
}
