"use client";

import { type ApiErrorLike, useErrorMessage } from "@/i18n/errors";
import { ApiError } from "@/lib/api";

// For these the backend message carries the specifics (which field, which host), so
// show it after the localized summary.
const WITH_DETAIL = new Set(["invalid_provider_config", "validation_error"]);

export function useDescribeError(): (error: unknown) => string {
  const errorMessage = useErrorMessage();
  return (error) => {
    const e: ApiErrorLike =
      error instanceof ApiError ? error : { code: "network_error", message: String(error) };
    const text = errorMessage(e);
    if (!WITH_DETAIL.has(e.code)) return text;
    const detail =
      error instanceof ApiError && error.issues.length > 0
        ? error.issues.map((i) => `${i.loc.slice(1).join(".")}: ${i.msg}`).join("; ")
        : e.message;
    return `${text} (${detail})`;
  };
}
