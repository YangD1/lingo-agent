import { type NextRequest, NextResponse } from "next/server";

import { AUTH_COOKIE, LOGIN_PATH } from "@/lib/auth";

/**
 * The backend rejected a token the proxy considered fresh (bad signature, rotated
 * JWT_SECRET, deleted user). Drop the cookie, or /login would bounce straight back
 * to the app and loop.
 */
export function GET(request: NextRequest) {
  const response = NextResponse.redirect(new URL(LOGIN_PATH, request.url));
  response.cookies.delete(AUTH_COOKIE);
  return response;
}
