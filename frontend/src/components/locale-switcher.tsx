"use client";

import { useLocale, useTranslations } from "next-intl";
import { useTransition } from "react";

import { Select } from "@/components/ui/select";
import { setLocale } from "@/i18n/actions";
import { locales } from "@/i18n/config";

export function LocaleSwitcher({ className }: { className?: string }) {
  const t = useTranslations("localeSwitcher");
  const locale = useLocale();
  const [pending, startTransition] = useTransition();

  return (
    <Select
      aria-label={t("label")}
      className={className}
      value={locale}
      disabled={pending}
      options={locales.map((value) => ({ value, label: t(value) }))}
      // Setting the cookie in a Server Action re-renders the page in the new language.
      onValueChange={(next) => startTransition(() => setLocale(next))}
    />
  );
}
