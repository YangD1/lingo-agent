"use client";

import { useLocale, useTranslations } from "next-intl";
import { useTransition } from "react";

import { NativeSelect } from "@/components/ui/native-select";
import { setLocale } from "@/i18n/actions";
import { locales } from "@/i18n/config";

export function LocaleSwitcher() {
  const t = useTranslations("localeSwitcher");
  const locale = useLocale();
  const [pending, startTransition] = useTransition();

  return (
    <NativeSelect
      aria-label={t("label")}
      value={locale}
      disabled={pending}
      onChange={(event) => {
        const next = event.target.value;
        // Setting the cookie in a Server Action re-renders the page in the new language.
        startTransition(() => setLocale(next));
      }}
    >
      {locales.map((value) => (
        <option key={value} value={value}>
          {t(value)}
        </option>
      ))}
    </NativeSelect>
  );
}
