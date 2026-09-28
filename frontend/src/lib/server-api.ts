import "server-only";

import { cookies } from "next/headers";

import { ApiError, toApiError } from "./api";

// Server components call the backend directly (not through the rewrite), forwarding
// the browser's cookies. Read at runtime, unlike the rewrite target in next.config.ts.
const backendUrl = () => process.env.BACKEND_URL ?? "http://localhost:8000";

export async function serverApi<T>(path: string): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${backendUrl()}${path}`, {
      headers: { cookie: (await cookies()).toString() },
      cache: "no-store",
    });
  } catch {
    throw new ApiError(0, "network_error", "backend unreachable");
  }
  if (!response.ok) throw await toApiError(response);
  return (await response.json()) as T;
}
