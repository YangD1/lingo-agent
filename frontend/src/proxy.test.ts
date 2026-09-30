// @vitest-environment node
// Next 16.3 docs call it unstable_doesProxyMatch, but only the old name is exported.
import { getRedirectUrl, unstable_doesMiddlewareMatch } from "next/experimental/testing/server";
import { NextRequest } from "next/server";
import { describe, expect, it } from "vitest";

import { AUTH_COOKIE } from "@/lib/auth";
import { fakeJwt } from "@/test/jwt";

import { config, proxy } from "./proxy";

const fresh = fakeJwt({ sub: "u", exp: Date.now() / 1000 + 3600 });
const expired = fakeJwt({ sub: "u", exp: Date.now() / 1000 - 1 });

function request(path: string, token?: string) {
  const req = new NextRequest(`http://localhost${path}`);
  if (token) req.cookies.set(AUTH_COOKIE, token);
  return req;
}

describe("proxy", () => {
  it("sends anonymous users to /login, remembering where they were going", () => {
    const response = proxy(request("/settings?tab=usage"));
    expect(getRedirectUrl(response)).toBe(
      "http://localhost/login?next=%2Fsettings%3Ftab%3Dusage",
    );
  });

  it("treats an expired token as logged out", () => {
    expect(getRedirectUrl(proxy(request("/chat", expired)))).toBe(
      "http://localhost/login?next=%2Fchat",
    );
  });

  it("lets logged-in users into the app", () => {
    expect(getRedirectUrl(proxy(request("/chat", fresh)))).toBeNull();
  });

  it.each(["/", "/login", "/register"])("sends logged-in users from %s to /dashboard", (path) => {
    expect(getRedirectUrl(proxy(request(path, fresh)))).toBe("http://localhost/dashboard");
  });

  it.each(["/", "/login", "/register"])("shows %s to anonymous users", (path) => {
    expect(getRedirectUrl(proxy(request(path)))).toBeNull();
  });

  it.each([
    ["/dashboard", true],
    ["/chat/abc", true],
    ["/placement", true],
    ["/memory", true],
    ["/learner", true],
    ["/vocab", true],
    ["/vocab/review", true],
    ["/settings", true],
    ["/api/auth/me", false],
    ["/session-expired", false],
    ["/_next/static/chunk.js", false],
  ])("matcher: %s -> %s", (url, expected) => {
    expect(unstable_doesMiddlewareMatch({ config, url })).toBe(expected);
  });
});
