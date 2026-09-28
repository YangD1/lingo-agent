import { getRequestConfig } from "next-intl/server";
import { cookies, headers } from "next/headers";

import { LOCALE_COOKIE, resolveLocale } from "./config";

// No locale in the URL (ADR 0006): the cookie wins, otherwise the browser's languages.
export default getRequestConfig(async () => {
  const locale = resolveLocale(
    (await cookies()).get(LOCALE_COOKIE)?.value,
    (await headers()).get("accept-language"),
  );
  return {
    locale,
    messages: (await import(`../../messages/${locale}.json`)).default,
  };
});
