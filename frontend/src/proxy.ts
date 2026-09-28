import { type NextRequest, NextResponse } from "next/server";

import { AUTH_COOKIE, HOME_PATH, LOGIN_PATH, hasFreshToken } from "@/lib/auth";

const AUTH_PAGES = new Set(["/login", "/register"]);

/**
 * Route guard only (i18n needs no proxy, see ADR 0006). Optimistic: it checks that a
 * non-expired token exists; the (app) layout verifies it with the backend.
 */
export function proxy(request: NextRequest) {
  const { pathname, search } = request.nextUrl;
  const loggedIn = hasFreshToken(request.cookies.get(AUTH_COOKIE)?.value);

  if (pathname === "/" || AUTH_PAGES.has(pathname)) {
    return loggedIn ? NextResponse.redirect(new URL(HOME_PATH, request.url)) : NextResponse.next();
  }
  if (loggedIn) return NextResponse.next();

  const login = new URL(LOGIN_PATH, request.url);
  login.searchParams.set("next", `${pathname}${search}`);
  return NextResponse.redirect(login);
}

export const config = {
  matcher: ["/", "/login", "/register", "/chat/:path*", "/settings/:path*"],
};
