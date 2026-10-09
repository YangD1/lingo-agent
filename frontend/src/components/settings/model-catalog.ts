import { ApiError, api } from "@/lib/api";
import { chatModelIds, speechModelIds, ttsModelIds } from "@/lib/models";
import type { ModelList } from "@/lib/types";

/**
 * The chat, speech-to-text or read-aloud models a connection serves, as its vendor lists
 * them (ADR 0007 §1); "all" for every id (an Azure speech connection lists its voices).
 */
export async function fetchModels(
  connectionId: string,
  use: "chat" | "speech" | "tts" | "all" = "chat",
): Promise<string[]> {
  const { models } = await api<ModelList>(`/tenant/connections/${connectionId}/models`);
  if (use === "all") return models.map((m) => m.id);
  if (use === "tts") return ttsModelIds(models);
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
