import { useTranslations } from "next-intl";

/** The body of every backend error: `{detail: {code, message}}` (ADR 0003 §3). */
export type ApiErrorLike = { code: string; message: string; retryAfter?: number | null };

/** Localized text for a backend error code, falling back to the backend's English message. */
export function useErrorMessage(): (error: ApiErrorLike) => string {
  const t = useTranslations("errors");
  return ({ code, message, retryAfter }) => {
    // Too many requests (ADR 0035): say how long to wait.
    if (code === "rate_limited") return t("rate_limited", { seconds: retryAfter ?? 1 });
    const key = code as Parameters<typeof t>[0];
    return t.has(key) ? t(key) : message;
  };
}
