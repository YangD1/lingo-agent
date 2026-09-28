import type { ApiErrorLike } from "@/i18n/errors";

/** Browser-side calls go through Next's `/api/*` rewrite, so the auth cookie is sent (ADR 0003). */
export const API_BASE = "/api";

/** One entry of a 422 `validation_error` (FastAPI's per-field detail). */
export type ValidationIssue = { loc: (string | number)[]; msg: string; type: string };

export class ApiError extends Error implements ApiErrorLike {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly issues: ValidationIssue[] = [],
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

/** Turn a non-2xx response into an ApiError; every backend error is `{detail: {code, message}}`. */
export async function toApiError(response: Response): Promise<ApiError> {
  const fallback = new ApiError(
    response.status,
    `http_${response.status}`,
    response.statusText || `HTTP ${response.status}`,
  );
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    return fallback; // e.g. a proxy's HTML error page
  }
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (detail && typeof detail === "object" && "code" in detail && "message" in detail) {
    const { code, message, errors } = detail as ApiErrorLike & { errors?: ValidationIssue[] };
    return new ApiError(response.status, code, message, errors ?? []);
  }
  return fallback;
}

/** fetch() that never rejects with a bare TypeError: offline becomes ApiError("network_error"). */
export async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, init);
  } catch (error) {
    if (isAbortError(error)) throw error;
    throw new ApiError(0, "network_error", "network request failed");
  }
  if (!response.ok) throw await toApiError(response);
  return response;
}

type JsonInit = Omit<RequestInit, "body"> & { json?: unknown };

/** JSON request/response helper; resolves to undefined for 204 No Content. */
export async function api<T>(path: string, { json, headers, ...init }: JsonInit = {}): Promise<T> {
  const response = await apiFetch(path, {
    ...init,
    headers:
      json === undefined ? headers : { "content-type": "application/json", ...headers },
    body: json === undefined ? undefined : JSON.stringify(json),
  });
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}
