"use client";

import { useFormatter, useTranslations } from "next-intl";
import { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Callout } from "@/components/ui/callout";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ErrorText } from "@/components/ui/error-text";
import { InlineConfirm } from "@/components/ui/inline-confirm";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api } from "@/lib/api";
import type { InvitePreview, Membership } from "@/lib/org";

import { QuotaUsageTable } from "./quota-fields";
import { useDescribeError } from "./use-describe-error";

/**
 * The main account this learner uses models from (ADR 0031): who, how much is left, and
 * leaving; or joining one with an invite code.
 */
export function MembershipSection() {
  const t = useTranslations("settings.org.membership");
  const format = useFormatter();
  const describe = useDescribeError();
  // undefined: loading; null: not a member.
  const [membership, setMembership] = useState<Membership | null | undefined>(undefined);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    api<Membership | null>("/org/membership").then(
      (m) => {
        setMembership(m);
        setError(null);
      },
      (e: unknown) => setError(describe(e)),
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps -- describe changes with locale only
  }, []);
  useEffect(() => load(), [load]);

  async function leave() {
    try {
      await api("/org/membership", { method: "DELETE" });
      load();
    } catch (e) {
      setError(describe(e));
    }
  }

  if (membership === undefined && !error) return null;

  return (
    <Card id="membership" className="scroll-mt-14 lg:scroll-mt-4">
      <CardHeader>
        <CardTitle>{t("title")}</CardTitle>
        <CardDescription>{t("description")}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {error && <ErrorText>{error}</ErrorText>}
        {membership === null && <JoinPanel onJoined={load} />}
        {membership && (
          <>
            <Callout tone="brand">
              {t("using", {
                name: membership.sponsor_name,
                date: format.dateTime(new Date(membership.joined_at), { dateStyle: "medium" }),
              })}
            </Callout>
            <QuotaUsageTable
              quotas={membership.quotas}
              usage={membership.usage}
              label={t("usage")}
            />
            <p className="text-sm text-muted-foreground">{t("ownFirst")}</p>
            <InlineConfirm
              question={t("leaveQuestion", { name: membership.sponsor_name })}
              confirmLabel={t("leave")}
              onConfirm={() => void leave()}
              className="self-start"
            >
              {(ask) => (
                <Button variant="outline" className="self-start" onClick={ask}>
                  {t("leave")}
                </Button>
              )}
            </InlineConfirm>
          </>
        )}
      </CardContent>
    </Card>
  );
}

/**
 * Join a main account with an invite code: first see what it shares, then agree (Q65i).
 * The /join page passes the code from the link.
 */
export function JoinPanel({ code: initial = "", onJoined }: { code?: string; onJoined: () => void }) {
  const t = useTranslations("settings.org.join");
  const describe = useDescribeError();
  const [code, setCode] = useState(initial);
  const [preview, setPreview] = useState<InvitePreview | null>(null);
  const [error, setError] = useState<string | null>(null);
  // A code from the link is looked up right away.
  const [busy, setBusy] = useState(!!initial);

  const fetchPreview = useCallback(
    (value: string) =>
      api<InvitePreview>("/org/join/preview", { method: "POST", json: { code: value } }).then(
        (p) => {
          setPreview(p);
          setError(null);
        },
        (e: unknown) => {
          setPreview(null);
          setError(describe(e));
        },
      ),
    // eslint-disable-next-line react-hooks/exhaustive-deps -- describe changes with locale only
    [],
  );
  function look(value: string) {
    setBusy(true);
    void fetchPreview(value).finally(() => setBusy(false));
  }
  useEffect(() => {
    if (initial) void fetchPreview(initial).finally(() => setBusy(false));
  }, [initial, fetchPreview]);

  async function join() {
    setBusy(true);
    try {
      await api("/org/join", { method: "POST", json: { code: code.trim() } });
      setError(null);
      onJoined();
    } catch (e) {
      setError(describe(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-3">
      {!preview && (
        <form
          className="flex flex-wrap items-end gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (code.trim()) look(code.trim());
          }}
        >
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="join-code">{t("code")}</Label>
            <Input
              id="join-code"
              value={code}
              autoComplete="off"
              onChange={(e) => setCode(e.target.value)}
              className="w-72 font-mono"
            />
          </div>
          <Button type="submit" variant="outline" disabled={!code.trim() || busy}>
            {t("look")}
          </Button>
        </form>
      )}
      {preview && (
        <>
          <p className="text-sm">{t("offer", { name: preview.sponsor_name })}</p>
          <QuotaUsageTable quotas={preview.quotas} label={t("quotas")} />
          <p className="text-sm text-muted-foreground">{t("privacy")}</p>
          <div className="flex gap-2">
            <Button onClick={() => void join()} disabled={busy}>
              {t("confirm", { name: preview.sponsor_name })}
            </Button>
            <Button variant="ghost" onClick={() => setPreview(null)} disabled={busy}>
              {t("cancel")}
            </Button>
          </div>
        </>
      )}
      {error && <ErrorText>{error}</ErrorText>}
    </div>
  );
}
