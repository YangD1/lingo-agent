// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";

import { api, ApiError } from "./api";

function mockFetch(response: Response | Error) {
  const fn = vi.fn(async () => {
    if (response instanceof Error) throw response;
    return response;
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("api", () => {
  it("prefixes /api and sends JSON bodies", async () => {
    const fetch = mockFetch(json({ id: "c1" }, 201));

    const result = await api<{ id: string }>("/conversations", { method: "POST", json: {} });

    expect(result).toEqual({ id: "c1" });
    const [url, init] = fetch.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/api/conversations");
    expect(init.body).toBe("{}");
    expect(init.headers).toEqual({ "content-type": "application/json" });
  });

  it("resolves 204 to undefined", async () => {
    mockFetch(new Response(null, { status: 204 }));
    await expect(api("/auth/logout", { method: "POST" })).resolves.toBeUndefined();
  });

  it("parses the backend error shape", async () => {
    mockFetch(json({ detail: { code: "email_taken", message: "email already registered" } }, 409));

    const error = await api("/auth/register").catch((e: unknown) => e);

    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 409, code: "email_taken" });
  });

  it("keeps per-field validation issues", async () => {
    const issue = { loc: ["body", "password"], msg: "too short", type: "string_too_short" };
    mockFetch(
      json({ detail: { code: "validation_error", message: "invalid", errors: [issue] } }, 422),
    );

    await expect(api("/auth/register")).rejects.toMatchObject({ issues: [issue] });
  });

  it("falls back to http_<status> for non-JSON errors", async () => {
    mockFetch(new Response("<html>Bad Gateway</html>", { status: 502, statusText: "Bad Gateway" }));

    await expect(api("/auth/me")).rejects.toMatchObject({
      code: "http_502",
      message: "Bad Gateway",
    });
  });

  it("reports network failures as network_error", async () => {
    mockFetch(new TypeError("fetch failed"));
    await expect(api("/auth/me")).rejects.toMatchObject({ status: 0, code: "network_error" });
  });

  it("lets aborts through untouched", async () => {
    mockFetch(new DOMException("aborted", "AbortError"));
    await expect(api("/auth/me")).rejects.toMatchObject({ name: "AbortError" });
  });
});
