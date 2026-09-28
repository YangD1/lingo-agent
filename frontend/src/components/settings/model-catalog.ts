import { ApiError, api } from "@/lib/api";
import { chatModelIds, speechModelIds } from "@/lib/models";
import type { ModelList } from "@/lib/types";

/** The chat or speech-to-text models a connection serves, as its vendor lists them (ADR 0007 §1). */
export async function fetchModels(
  connectionId: string,
  use: "chat" | "speech" = "chat",
): Promise<string[]> {
  const { models } = await api<ModelList>(`/tenant/connections/${connectionId}/models`);
  return use === "speech" ? speechModelIds(models) : chatModelIds(models);
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
