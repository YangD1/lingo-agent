import { ApiError, api } from "@/lib/api";
import { chatModelIds } from "@/lib/models";
import type { ModelList } from "@/lib/types";

/** The chat models a connection serves, as its vendor lists them (ADR 0007 §1). */
export async function fetchChatModels(connectionId: string): Promise<string[]> {
  return chatModelIds((await api<ModelList>(`/tenant/connections/${connectionId}/models`)).models);
}

/**
 * Why listing failed. model_list_failed carries the vendor's own reason (e.g. "HTTP 401: …"),
 * which is what the user needs; other errors get the usual localized text.
 */
export function modelListFailure(error: unknown, describe: (e: unknown) => string): string {
  return error instanceof ApiError && error.code === "model_list_failed"
    ? error.message
    : describe(error);
}
