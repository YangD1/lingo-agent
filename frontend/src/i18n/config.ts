export const locales = ["en", "zh-CN"] as const;
export type Locale = (typeof locales)[number];
export const defaultLocale: Locale = "en";

// Set only when the user picks a language; until then we follow Accept-Language.
export const LOCALE_COOKIE = "NEXT_LOCALE";

export function isLocale(value: unknown): value is Locale {
  return typeof value === "string" && (locales as readonly string[]).includes(value);
}

/** Map a primary language tag to a supported locale (all Chinese variants -> zh-CN for now). */
function matchTag(tag: string): Locale | undefined {
  const primary = tag.toLowerCase().split("-")[0];
  if (primary === "zh") return "zh-CN";
  if (primary === "en") return "en";
  return undefined;
}

/** Pick the best supported locale from an Accept-Language header, honoring q-values. */
export function negotiateLocale(acceptLanguage: string | null | undefined): Locale {
  if (!acceptLanguage) return defaultLocale;
  const ranked = acceptLanguage
    .split(",")
    .map((part, index) => {
      const [tag, ...params] = part.trim().split(";");
      const q = params.map((p) => p.trim()).find((p) => p.startsWith("q="));
      const quality = q === undefined ? 1 : Number(q.slice(2));
      return { tag: tag.trim(), quality: Number.isNaN(quality) ? 0 : quality, index };
    })
    .filter(({ tag, quality }) => tag && quality > 0)
    .sort((a, b) => b.quality - a.quality || a.index - b.index);
  for (const { tag } of ranked) {
    const locale = matchTag(tag);
    if (locale) return locale;
  }
  return defaultLocale;
}

export function resolveLocale(
  cookieValue: string | undefined,
  acceptLanguage: string | null | undefined,
): Locale {
  return isLocale(cookieValue) ? cookieValue : negotiateLocale(acceptLanguage);
}
