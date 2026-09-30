import { describe, expect, it } from "vitest";

import { fakeJwt } from "@/test/jwt";

import { hasFreshToken, safeNextPath } from "./auth";

describe("hasFreshToken", () => {
  const now = 1_800_000_000;

  it("accepts a token that expires in the future", () => {
    expect(hasFreshToken(fakeJwt({ sub: "u", exp: now + 60 }), now)).toBe(true);
  });

  it.each([
    ["missing", undefined],
    ["expired", fakeJwt({ sub: "u", exp: now - 1 })],
    ["without exp", fakeJwt({ sub: "u" })],
    ["not a JWT", "garbage"],
    ["with an undecodable payload", "a.!!!.c"],
  ])("rejects a token that is %s", (_, token) => {
    expect(hasFreshToken(token, now)).toBe(false);
  });
});

describe("safeNextPath", () => {
  it.each([
    ["/settings?tab=usage", "/settings?tab=usage"],
    [undefined, "/dashboard"],
    ["https://evil.example", "/dashboard"],
    ["//evil.example", "/dashboard"],
    ["/\\evil.example", "/dashboard"],
  ])("%s -> %s", (next, expected) => {
    expect(safeNextPath(next)).toBe(expected);
  });
});
