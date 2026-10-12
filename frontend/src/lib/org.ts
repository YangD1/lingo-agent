/**
 * Main accounts and members (ADR 0031): a main account lends its model connections to
 * members, within per-capability quotas. Mirrors `backend/app/api/org.py`.
 */

export const CAPABILITIES = ["text", "tts", "asr", "pronunciation", "realtime"] as const;
export type Capability = (typeof CAPABILITIES)[number];

/** What a capability's caps count (`app/org/quotas.py` UNITS). */
export const UNITS: Record<Capability, "tokens" | "characters" | "minutes"> = {
  text: "tokens",
  tts: "characters",
  asr: "minutes",
  pronunciation: "minutes",
  realtime: "minutes",
};

/** null: no cap; 0: none allowed. Days and months are UTC. */
export type Limit = { daily: number | null; monthly: number | null };
export type Quotas = Record<Capability, Limit>;
/** In the capability's unit. */
export type Used = { day: number; month: number };
export type QuotaUsage = Record<Capability, Used>;

export type Invite = {
  id: string;
  expires_at: string;
  /** null: any number of people may join with it. */
  max_uses: number | null;
  used_count: number;
  created_at: string;
};
/** Only the create call returns the code: the backend keeps its hash. */
export type CreatedInvite = Invite & { code: string };

export type Member = {
  id: string;
  display_name: string | null;
  email: string;
  status: "active" | "left" | "removed";
  joined_at: string;
  ended_at: string | null;
  quotas: Quotas;
  usage: QuotaUsage;
};

export type Membership = {
  sponsor_name: string;
  joined_at: string;
  quotas: Quotas;
  usage: QuotaUsage;
};

export type InvitePreview = { sponsor_name: string; quotas: Quotas; expires_at: string };

export function joinLink(code: string, origin: string = window.location.origin): string {
  return `${origin}/join?code=${encodeURIComponent(code)}`;
}

/** What's left under the tighter cap, never below 0; null: no cap. */
export function left(limit: Limit, used: Used): number | null {
  const caps = [
    limit.daily === null ? null : limit.daily - used.day,
    limit.monthly === null ? null : limit.monthly - used.month,
  ].filter((v): v is number => v !== null);
  return caps.length ? Math.max(0, Math.min(...caps)) : null;
}

/** Capabilities the member gets nothing of: a cap at 0. */
export function isOff(limit: Limit): boolean {
  return limit.daily === 0 || limit.monthly === 0;
}
