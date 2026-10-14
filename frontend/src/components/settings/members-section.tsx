"use client";

import { Check, Copy } from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";
import { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ErrorText } from "@/components/ui/error-text";
import { InlineConfirm } from "@/components/ui/inline-confirm";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Segmented } from "@/components/ui/segmented";
import { Tag } from "@/components/ui/tag";
import { ApiError, api } from "@/lib/api";
import { type CreatedInvite, type Invite, type Member, type Quotas, joinLink } from "@/lib/org";

import { QuotaFields, QuotaUsageTable, fromDraft, toDraft } from "./quota-fields";
import { useDescribeError } from "./use-describe-error";

const INVITE_DAYS = [1, 7, 30] as const;

/**
 * Members (ADR 0031): people this account lends its model connections to. Invite links,
 * each member's use and quotas, and the quotas new members start with. The main
 * account never sees members' learning data, only their use (Q65c).
 */
export function MembersSection() {
  const t = useTranslations("settings.org");
  const describe = useDescribeError();
  // null: not loaded yet, or not a tenant manager (403): the card stays hidden.
  const [members, setMembers] = useState<Member[] | null>(null);
  const [invites, setInvites] = useState<Invite[]>([]);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    Promise.all([api<Member[]>("/org/members"), api<Invite[]>("/org/invites")]).then(
      ([m, i]) => {
        setMembers(m);
        setInvites(i);
        setError(null);
      },
      (e: unknown) => {
        if (!(e instanceof ApiError && e.status === 403)) setError(describe(e));
      },
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps -- describe changes with locale only
  }, []);
  useEffect(() => load(), [load]);

  if (!members && !error) return null;

  const active = members?.filter((m) => m.status === "active") ?? [];
  const past = members?.filter((m) => m.status !== "active") ?? [];

  return (
    <Card id="members" className="scroll-mt-14 lg:scroll-mt-4">
      <CardHeader>
        <CardTitle>{t("members.title")}</CardTitle>
        <CardDescription>{t("members.description")}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-5">
        {error && <ErrorText>{error}</ErrorText>}
        <InviteForm onCreated={load} />
        {invites.length > 0 && <InviteList invites={invites} onChange={load} />}
        {members && (
          <section className="flex flex-col gap-2" aria-label={t("members.list")}>
            <h3 className="text-sm font-semibold">{t("members.list")}</h3>
            {active.length === 0 ? (
              <p className="rounded-lg border border-dashed px-4 py-6 text-center text-sm text-muted-foreground">
                {t("members.empty")}
              </p>
            ) : (
              active.map((m) => <MemberRow key={m.id} member={m} onChange={load} />)
            )}
            {past.length > 0 && (
              <details className="text-sm">
                <summary className="cursor-pointer text-muted-foreground">
                  {t("members.past", { count: past.length })}
                </summary>
                <ul className="mt-2 flex flex-col gap-1">
                  {past.map((m) => (
                    <li key={m.id} className="flex flex-wrap items-center gap-2">
                      <span>{m.display_name ?? m.email}</span>
                      <span className="text-xs text-muted-foreground">{m.email}</span>
                      <Tag variant="outline">{t(`members.status.${m.status}`)}</Tag>
                    </li>
                  ))}
                </ul>
              </details>
            )}
          </section>
        )}
        <DefaultQuotas />
      </CardContent>
    </Card>
  );
}

function InviteForm({ onCreated }: { onCreated: () => void }) {
  const t = useTranslations("settings.org.invite");
  const describe = useDescribeError();
  const [days, setDays] = useState<number>(7);
  // "": anyone with the link, any number of times.
  const [uses, setUses] = useState("1");
  const [created, setCreated] = useState<CreatedInvite | null>(null);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const usesValue = uses.trim() === "" ? null : Number(uses);
  const usesValid = usesValue === null || (Number.isInteger(usesValue) && usesValue >= 1 && usesValue <= 1000);

  async function create() {
    try {
      const invite = await api<CreatedInvite>("/org/invites", {
        method: "POST",
        json: { days, max_uses: usesValue },
      });
      setCreated(invite);
      setCopied(false);
      setError(null);
      onCreated();
    } catch (e) {
      setError(describe(e));
    }
  }

  const link = created ? joinLink(created.code) : null;

  return (
    <section className="flex flex-col gap-2" aria-label={t("title")}>
      <h3 className="text-sm font-semibold">{t("title")}</h3>
      <form
        className="flex flex-wrap items-end gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          void create();
        }}
      >
        <div className="flex flex-col gap-1.5">
          <span className="text-sm leading-none font-medium">{t("days")}</span>
          <Segmented
            label={t("days")}
            className="flex h-10 md:h-9 [&>button]:h-full"
            value={String(days)}
            onChange={(d) => setDays(Number(d))}
            options={INVITE_DAYS.map((d) => ({ value: String(d), label: t("daysOption", { days: d }) }))}
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="invite-uses">{t("uses")}</Label>
          <Input
            id="invite-uses"
            type="number"
            inputMode="numeric"
            min={1}
            placeholder={t("anyUses")}
            value={uses}
            aria-invalid={!usesValid}
            onChange={(e) => setUses(e.target.value)}
            className="w-28"
          />
        </div>
        <Button type="submit" disabled={!usesValid}>
          {t("create")}
        </Button>
      </form>
      {error && <ErrorText>{error}</ErrorText>}
      {link && (
        <div className="flex flex-col gap-1.5 rounded-lg border bg-muted/40 p-3">
          <p className="text-sm">{t("createdHint")}</p>
          <div className="flex items-center gap-2">
            <Input readOnly value={link} aria-label={t("link")} className="font-mono text-xs" onFocus={(e) => e.target.select()} />
            <Button
              type="button"
              variant="outline"
              size="icon"
              aria-label={t("copy")}
              title={t("copy")}
              onClick={() => {
                void navigator.clipboard?.writeText(link).then(() => setCopied(true), () => {});
              }}
            >
              {copied ? <Check /> : <Copy />}
            </Button>
          </div>
          <p className="text-xs text-muted-foreground">{t("code", { code: created!.code })}</p>
        </div>
      )}
    </section>
  );
}

function InviteList({ invites, onChange }: { invites: Invite[]; onChange: () => void }) {
  const t = useTranslations("settings.org.invite");
  const format = useFormatter();
  const describe = useDescribeError();
  const [error, setError] = useState<string | null>(null);

  async function revoke(id: string) {
    try {
      await api(`/org/invites/${id}`, { method: "DELETE" });
      setError(null);
      onChange();
    } catch (e) {
      setError(describe(e));
    }
  }

  return (
    <section className="flex flex-col gap-1.5" aria-label={t("open")}>
      <h3 className="text-sm font-semibold">{t("open")}</h3>
      <ul className="flex flex-col gap-1 text-sm">
        {invites.map((i) => (
          <li key={i.id} className="flex flex-wrap items-center justify-between gap-2">
            <span className="text-muted-foreground">
              {t("openRow", {
                expires: format.dateTime(new Date(i.expires_at), { dateStyle: "medium", timeStyle: "short" }),
                used: i.used_count,
                max: i.max_uses ?? "∞",
              })}
            </span>
            <InlineConfirm question={t("revokeQuestion")} confirmLabel={t("revoke")} onConfirm={() => void revoke(i.id)}>
              {(ask) => (
                <Button variant="ghost" size="sm" onClick={ask}>
                  {t("revoke")}
                </Button>
              )}
            </InlineConfirm>
          </li>
        ))}
      </ul>
      {error && <ErrorText>{error}</ErrorText>}
    </section>
  );
}

function MemberRow({ member, onChange }: { member: Member; onChange: () => void }) {
  const t = useTranslations("settings.org.members");
  const format = useFormatter();
  const describe = useDescribeError();
  const [editing, setEditing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function remove() {
    try {
      await api(`/org/members/${member.id}`, { method: "DELETE" });
      setError(null);
      onChange();
    } catch (e) {
      setError(describe(e));
    }
  }

  const name = member.display_name ?? member.email;
  return (
    <div className="flex flex-col gap-2 rounded-lg border p-3" data-testid="member-row">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate text-sm font-medium">{name}</p>
          <p className="truncate text-xs text-muted-foreground">
            {t("joined", {
              email: member.email,
              date: format.dateTime(new Date(member.joined_at), { dateStyle: "medium" }),
            })}
          </p>
        </div>
        <div className="flex items-center gap-1">
          <Button variant="outline" size="sm" onClick={() => setEditing((v) => !v)} aria-expanded={editing}>
            {t("editQuotas")}
          </Button>
          <InlineConfirm
            question={t("removeQuestion", { name })}
            confirmLabel={t("remove")}
            onConfirm={() => void remove()}
          >
            {(ask) => (
              <Button variant="ghost" size="sm" onClick={ask}>
                {t("remove")}
              </Button>
            )}
          </InlineConfirm>
        </div>
      </div>
      {editing ? (
        <QuotaEditor
          idPrefix={`member-${member.id}`}
          quotas={member.quotas}
          path={`/org/members/${member.id}/quotas`}
          onSaved={() => {
            setEditing(false);
            onChange();
          }}
          onCancel={() => setEditing(false)}
        />
      ) : (
        <QuotaUsageTable quotas={member.quotas} usage={member.usage} label={t("usageOf", { name })} />
      )}
      {error && <ErrorText>{error}</ErrorText>}
    </div>
  );
}

function QuotaEditor({
  idPrefix,
  quotas,
  path,
  onSaved,
  onCancel,
}: {
  idPrefix: string;
  quotas: Quotas;
  path: string;
  onSaved: (quotas: Quotas) => void;
  onCancel?: () => void;
}) {
  const t = useTranslations("settings.org");
  const describe = useDescribeError();
  const [draft, setDraft] = useState(() => toDraft(quotas));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const parsed = fromDraft(draft);
  const changed = parsed !== null && JSON.stringify(parsed) !== JSON.stringify(quotas);

  async function save() {
    if (!parsed) return;
    setSaving(true);
    try {
      await api(path, { method: "PUT", json: parsed });
      setError(null);
      onSaved(parsed);
    } catch (e) {
      setError(describe(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <form
      className="flex flex-col gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        void save();
      }}
    >
      <QuotaFields idPrefix={idPrefix} draft={draft} onChange={setDraft} />
      <div className="flex gap-2">
        <Button type="submit" disabled={!changed || saving}>
          {t("save")}
        </Button>
        {onCancel && (
          <Button type="button" variant="ghost" onClick={onCancel}>
            {t("cancel")}
          </Button>
        )}
      </div>
      {error && <ErrorText>{error}</ErrorText>}
    </form>
  );
}

function DefaultQuotas() {
  const t = useTranslations("settings.org.defaults");
  const [quotas, setQuotas] = useState<Quotas | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    api<Quotas>("/org/default-quotas").then(setQuotas, () => {});
  }, []);

  if (!quotas) return null;
  return (
    <details className="flex flex-col gap-2">
      <summary className="cursor-pointer text-sm font-semibold">{t("title")}</summary>
      <p className="my-2 text-sm text-muted-foreground">{t("hint")}</p>
      <QuotaEditor
        // Keyed by what is stored: saving resets the drafts to it.
        key={JSON.stringify(quotas)}
        idPrefix="default-quotas"
        quotas={quotas}
        path="/org/default-quotas"
        onSaved={(q) => {
          setQuotas(q);
          setSaved(true);
        }}
      />
      {saved && <p className="text-sm text-success">{t("saved")}</p>}
    </details>
  );
}
