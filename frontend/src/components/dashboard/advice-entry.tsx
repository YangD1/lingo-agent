"use client";

import Link from "next/link";
import { useFormatter, useLocale, useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import { PracticeChoices } from "@/components/practice/practice-choices";
import { useDescribeError } from "@/components/settings/use-describe-error";
import { buttonVariants } from "@/components/ui/button";
import { type Advice, type AdviceItem, adviceHref, fetchAdvice, templateKey } from "@/lib/advice";
import { kcName, learnerHref } from "@/lib/learner";

const linkClass = "ml-auto text-[13px] font-medium text-primary underline-offset-2 hover:underline";

/** The learning engine's candidates for now (ADR 0016 §3): rules only, no model. */
export function useAdvice() {
  const describe = useDescribeError();
  const [advice, setAdvice] = useState<Advice | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    fetchAdvice().then(setAdvice, (e: unknown) => setError(describe(e)));
    // eslint-disable-next-line react-hooks/exhaustive-deps -- describe is stable enough
  }, []);
  return { advice, error };
}

/** One candidate as a link: the fallback when no chat model is set up. */
export function AdviceEntry({ item }: { item: AdviceItem }) {
  const t = useTranslations("dashboard.advice");
  const locale = useLocale();
  const key = templateKey(item);
  const kc = item.kc ? kcName(item.kc, locale) : "";
  const book = item.book ? (locale.startsWith("zh") ? item.book.name_zh : item.book.name_en) : "";
  return (
    <li
      className="flex flex-col gap-2 rounded-lg border bg-card p-3.5"
      data-testid="advice-item"
      data-kind={item.kind}
    >
      <span className="text-sm font-semibold">{t(`kinds.${key}.title`, { kc })}</span>
      <p className="flex-1 text-[13px] text-muted-foreground">{t(`kinds.${key}.reason`, { book })}</p>
      <Evidence item={item} kc={kc} />
      <div className="mt-1 flex flex-wrap items-center gap-3">
        {item.kind === "grammar_practice" && item.kc ? (
          <>
            <PracticeChoices kcId={item.kc.id} origin="dashboard" />
            <Link href={learnerHref(item.kc.id)} className={linkClass}>
              {t("evidenceLink")}
            </Link>
          </>
        ) : (
          <Link href={adviceHref(item)} className={buttonVariants({ size: "sm" })}>
            {t(`kinds.${key}.action`)}
          </Link>
        )}
      </div>
    </li>
  );
}

function Evidence({ item, kc }: { item: AdviceItem; kc: string }) {
  const t = useTranslations("dashboard.advice.evidence");
  const format = useFormatter();
  let text: string | null = null;
  switch (item.kind) {
    case "vocab_review":
      text = t("due", { n: item.count ?? 0 });
      break;
    case "vocab_learn":
      text = t("newLeft", { n: item.count ?? 0 });
      break;
    case "placement":
      if (item.in_progress) text = t("inProgress");
      else if (item.reason === "progress")
        text = t("learned", { level: item.level ?? "", learned: item.learned ?? 0, total: item.total ?? 0 });
      else if (item.days_since !== null) text = t("lastTest", { n: item.days_since });
      break;
    case "grammar_practice":
      text = t("grammar", {
        kc,
        n: item.count ?? 0,
        p: format.number(item.p_mastery ?? 0, { style: "percent" }),
      });
      break;
  }
  return text ? (
    <p className="self-start rounded-[6px] border px-[7px] py-0.5 text-[11.5px] text-muted-foreground" data-testid="advice-evidence">
      {text}
    </p>
  ) : null;
}
