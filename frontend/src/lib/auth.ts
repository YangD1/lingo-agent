/** Name of the httpOnly cookie the backend sets on login (backend/app/deps.py). */
export const AUTH_COOKIE = "lingo_access_token";

export const LOGIN_PATH = "/login";
export const HOME_PATH = "/dashboard";

/**
 * Optimistic check for the proxy: is there a token that hasn't expired yet?
 * The signature is NOT verified here - the backend does that on every API call, and
 * the (app) layout asks the backend (/auth/me) before rendering anything private.
 */
export function hasFreshToken(token: string | undefined, nowSeconds = Date.now() / 1000): boolean {
  if (!token) return false;
  const payload = token.split(".")[1];
  if (!payload) return false;
  try {
    const base64 = payload.replace(/-/g, "+").replace(/_/g, "/");
    const { exp } = JSON.parse(atob(base64.padEnd(Math.ceil(base64.length / 4) * 4, "="))) as {
      exp?: unknown;
    };
    return typeof exp === "number" && exp > nowSeconds;
  } catch {
    return false;
  }
}

/** Only same-origin paths are allowed as post-login redirects (no open redirect). */
export function safeNextPath(next: string | null | undefined): string {
  if (!next || !next.startsWith("/") || next.startsWith("//") || next.startsWith("/\\")) {
    return HOME_PATH;
  }
  return next;
}
