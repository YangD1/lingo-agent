"use client";

import { ListChecks, MessageCircle } from "lucide-react";
import { useTranslations } from "next-intl";
import Link from "next/link";

import { AiBadge } from "@/components/ai-badge";
import { buttonVariants } from "@/components/ui/button";
import { practiceHref } from "@/lib/learner";
import { type Origin, practiceSetHref } from "@/lib/practice";
import { cn } from "@/lib/utils";

/**
 * The two ways to practise one grammar point (Q35b): a set of questions, first, and a
 * practice conversation with the tutor.
 */
export function PracticeChoices({
  kcId,
  origin,
  className,
}: {
  kcId: string;
  origin: Origin;
  className?: string;
}) {
  const t = useTranslations("practice.entry");
  return (
    <span className={cn("inline-flex flex-wrap items-center gap-2", className)}>
      <span className="inline-flex items-center gap-1.5">
        <Link href={practiceSetHref(origin, kcId)} className={buttonVariants({ size: "sm" })}>
          <ListChecks />
          {t("exercises")}
        </Link>
        <AiBadge feature={["practice_set", "practice_grade"]} />
      </span>
      <span className="inline-flex items-center gap-1.5">
        <Link href={practiceHref(kcId)} className={buttonVariants({ size: "sm", variant: "outline" })}>
          <MessageCircle />
          {t("chat")}
        </Link>
        <AiBadge feature="practice_start" />
      </span>
    </span>
  );
}
