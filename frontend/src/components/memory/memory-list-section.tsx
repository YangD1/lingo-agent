"use client";

import { ChevronDown, ChevronRight, Pencil, RotateCcw, Trash2 } from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";
import Link from "next/link";
import { useEffect, useState } from "react";

import { AiBadge } from "@/components/ai-badge";
import { useDescribeError } from "@/components/settings/use-describe-error";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { InlineConfirm } from "@/components/ui/inline-confirm";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { ErrorText } from "@/components/ui/error-text";
import { api } from "@/lib/api";
import { currentVersion, factHistory, withHistory } from "@/lib/memory-history";
import type { Memory, MemoryKind } from "@/lib/types";
import { EmptyState } from "@/components/ui/empty-state";

const MAX_LENGTH = 1000; // backend/app/memory/service.py MAX_CONTENT_LENGTH

/**
 * Facts can be added and edited by the learner; conversation summaries are written by the
 * tutor and can only be deleted. Deleting is real deletion (ADR 0009), and takes a fact's
 * earlier versions with it. Facts the tutor rewrote or dropped are listed at the bottom,
 * where they can be restored (ADR 0053 §4).
 */
export function MemoryListSection({ kind }: { kind: MemoryKind }) {
  const t = useTranslations(`memory.${kind}`);
  const common = useTranslations("memory");
  const describe = useDescribeError();
  const [memories, setMemories] = useState<Memory[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [editing, setEditing] = useState<{ id: string; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const editable = kind === "fact";

  useEffect(() => {
    const query = editable ? `kind=${kind}&include_superseded=true` : `kind=${kind}`;
    api<Memory[]>(`/memories?${query}`).then(setMemories, (e: unknown) => setError(describe(e)));
    // eslint-disable-next-line react-hooks/exhaustive-deps -- load once
  }, [kind]);

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (e) {
      setError(describe(e));
    } finally {
      setBusy(false);
    }
  }

  const add = () =>
    run(async () => {
      const created = await api<Memory>("/memories", {
        method: "POST",
        json: { content: draft },
      });
      setMemories((ms) => [created, ...(ms ?? [])]);
      setDraft("");
    });

  const saveEdit = () =>
    run(async () => {
      if (!editing) return;
      const updated = await api<Memory>(`/memories/${editing.id}`, {
        method: "PATCH",
        json: { content: editing.text },
      });
      // Newest first, like the backend's order.
      setMemories((ms) => [updated, ...(ms ?? []).filter((m) => m.id !== updated.id)]);
      setEditing(null);
    });

  const remove = (memory: Memory) =>
    run(async () => {
      await api(`/memories/${memory.id}`, { method: "DELETE" });
      setMemories((ms) => {
        const gone = withHistory(memory.id, ms ?? []);
        return (ms ?? []).filter((m) => !gone.has(m.id));
      });
    });

  const restore = (memory: Memory) =>
    run(async () => {
      const restored = await api<Memory>(`/memories/${memory.id}/restore`, { method: "POST" });
      setMemories((ms) => [restored, ...(ms ?? []).filter((m) => m.id !== restored.id)]);
    });

  const history = memories && editable ? factHistory(memories) : null;
  const shown = history ? history.active : memories;

  const clear = () =>
    run(async () => {
      await api(`/memories?kind=${kind}`, { method: "DELETE" });
      setMemories([]);
    });

  return (
    <Card data-testid={`memories-${kind}`}>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          {t("title")}
          <AiBadge feature="memory_edit" />
        </CardTitle>
        <CardDescription>{t("description")}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {editable && (
          <form
            className="flex gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              void add();
            }}
          >
            <Input
              aria-label={t("addLabel")}
              placeholder={t("addPlaceholder")}
              value={draft}
              maxLength={MAX_LENGTH}
              onChange={(e) => setDraft(e.target.value)}
            />
            <Button type="submit" disabled={busy || !draft.trim()} className="shrink-0">
              {t("add")}
            </Button>
          </form>
        )}
        {error &&
          (memories ? (
            <ErrorText>{error}</ErrorText>
          ) : (
            // Nothing loaded: the whole area failed, so the big oops cat.
            <EmptyState tone="error" title={error} />
          ))}
        {shown && shown.length === 0 && (
          <p className="rounded-lg border border-dashed px-4 py-6 text-center text-sm text-muted-foreground">
            {t("empty")}
          </p>
        )}
        {memories && memories.length > 0 && (
          <>
            {shown && shown.length > 0 && (
              <ul className="flex flex-col divide-y border-y" aria-label={t("title")}>
                {shown.map((m) => (
                  <li key={m.id} className="flex flex-col gap-1 py-3">
                    {editing?.id === m.id ? (
                      <form
                        className="flex items-start gap-2"
                        onSubmit={(e) => {
                          e.preventDefault();
                          void saveEdit();
                        }}
                      >
                        <Textarea
                          aria-label={common("editLabel")}
                          value={editing.text}
                          maxLength={MAX_LENGTH}
                          autoFocus
                          onChange={(e) => setEditing({ id: m.id, text: e.target.value })}
                          className="min-h-16 flex-1"
                        />
                        <div className="flex shrink-0 flex-col gap-1">
                          <Button type="submit" size="sm" disabled={busy || !editing.text.trim()}>
                            {common("save")}
                          </Button>
                          <Button
                            type="button"
                            size="sm"
                            variant="ghost"
                            onClick={() => setEditing(null)}
                          >
                            {common("cancel")}
                          </Button>
                        </div>
                      </form>
                    ) : (
                      <div className="flex items-start gap-2">
                        <div className="flex min-w-0 flex-1 flex-col gap-1">
                          {editable ? (
                            <>
                              <p className="text-sm whitespace-pre-wrap">{m.content}</p>
                              <MemoryMeta memory={m} />
                              <EarlierVersions versions={history?.earlier.get(m.id) ?? []} />
                            </>
                          ) : (
                            <>
                              <MemoryMeta memory={m} titleFirst />
                              <p className="text-[13px] whitespace-pre-wrap text-muted-foreground">
                                {m.content}
                              </p>
                            </>
                          )}
                        </div>
                        {editable && (
                          <Button
                            size="icon-sm"
                            variant="ghost"
                            aria-label={common("edit")}
                            disabled={busy}
                            className="text-muted-foreground hover:text-foreground"
                            onClick={() => setEditing({ id: m.id, text: m.content })}
                          >
                            <Pencil />
                          </Button>
                        )}
                        <InlineConfirm question={t("confirmDelete")} onConfirm={() => void remove(m)}>
                          {(ask) => (
                            <Button
                              size="icon-sm"
                              variant="ghost"
                              aria-label={common("delete")}
                              disabled={busy}
                              className="text-muted-foreground hover:text-foreground"
                              onClick={ask}
                            >
                              <Trash2 />
                            </Button>
                          )}
                        </InlineConfirm>
                      </div>
                    )}
                  </li>
                ))}
              </ul>
            )}
            {history && history.superseded.length > 0 && (
              <SupersededFacts
                memories={memories}
                superseded={history.superseded}
                busy={busy}
                onRestore={(m) => void restore(m)}
                onDelete={(m) => void remove(m)}
              />
            )}
            <div>
              <ConfirmDialog
                trigger={
                  <Button size="sm" variant="destructive" disabled={busy}>
                    {t("clear")}
                  </Button>
                }
                title={t("clear")}
                description={t("confirmClear")}
                onConfirm={() => void clear()}
              />
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}

/** The versions a fact replaced, folded under it. */
function EarlierVersions({ versions }: { versions: Memory[] }) {
  const t = useTranslations("memory.fact");
  const [open, setOpen] = useState(false);
  if (versions.length === 0) return null;
  const Icon = open ? ChevronDown : ChevronRight;
  return (
    <div className="text-xs text-muted-foreground">
      <button
        type="button"
        aria-expanded={open}
        className="inline-flex items-center gap-0.5 hover:text-foreground"
        onClick={() => setOpen(!open)}
      >
        <Icon className="size-3.5" />
        {t("earlier", { count: versions.length })}
      </button>
      {open && (
        <ul className="mt-1 flex flex-col gap-0.5 border-l pl-3">
          {versions.map((v) => (
            <li key={v.id} className="whitespace-pre-wrap">
              {v.content}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** What the tutor rewrote or dropped: no longer used, folded away until asked for. */
function SupersededFacts({
  memories,
  superseded,
  busy,
  onRestore,
  onDelete,
}: {
  memories: Memory[];
  superseded: Memory[];
  busy: boolean;
  onRestore: (memory: Memory) => void;
  onDelete: (memory: Memory) => void;
}) {
  const t = useTranslations("memory.fact");
  const common = useTranslations("memory");
  const [open, setOpen] = useState(false);
  const byId = new Map(memories.map((m) => [m.id, m]));
  const Icon = open ? ChevronDown : ChevronRight;
  return (
    <section className="flex flex-col gap-2" data-testid="memories-superseded">
      <button
        type="button"
        aria-expanded={open}
        className="inline-flex items-center gap-1 self-start text-sm text-muted-foreground hover:text-foreground"
        onClick={() => setOpen(!open)}
      >
        <Icon className="size-4" />
        {t("supersededTitle", { count: superseded.length })}
      </button>
      {open && (
        <>
          <p className="text-xs text-muted-foreground">{t("supersededHint")}</p>
          <ul
            className="flex flex-col divide-y border-y"
            aria-label={t("supersededTitle", { count: superseded.length })}
          >
            {superseded.map((m) => {
              const now = currentVersion(m, byId);
              return (
                <li key={m.id} className="flex items-start gap-2 py-3">
                  <div className="flex min-w-0 flex-1 flex-col gap-1">
                    <p className="text-sm whitespace-pre-wrap text-muted-foreground">{m.content}</p>
                    <p className="text-xs text-muted-foreground">
                      {now ? t("replacedWith", { content: now.content }) : t("dropped")}
                    </p>
                  </div>
                  <Button
                    size="icon-sm"
                    variant="ghost"
                    aria-label={t("restore")}
                    title={t("restore")}
                    disabled={busy}
                    className="text-muted-foreground hover:text-foreground"
                    onClick={() => onRestore(m)}
                  >
                    <RotateCcw />
                  </Button>
                  <InlineConfirm question={t("confirmDeleteOld")} onConfirm={() => onDelete(m)}>
                    {(ask) => (
                      <Button
                        size="icon-sm"
                        variant="ghost"
                        aria-label={common("delete")}
                        disabled={busy}
                        className="text-muted-foreground hover:text-foreground"
                        onClick={ask}
                      >
                        <Trash2 />
                      </Button>
                    )}
                  </InlineConfirm>
                </li>
              );
            })}
          </ul>
        </>
      )}
    </section>
  );
}

/**
 * When and where a memory came from. Facts put it under the text; summaries lead with the
 * conversation's title, which is what the learner recognises them by.
 */
function MemoryMeta({ memory: m, titleFirst = false }: { memory: Memory; titleFirst?: boolean }) {
  const common = useTranslations("memory");
  const format = useFormatter();
  const updated = new Date(m.updated_at);
  const date = (
    <time
      dateTime={m.updated_at}
      title={format.dateTime(updated, { dateStyle: "medium", timeStyle: "short" })}
      className="font-mono text-xs text-muted-foreground"
    >
      {format.dateTime(updated, { month: "2-digit", day: "2-digit" })}
    </time>
  );
  const href = m.source_conversation_id ? `/chat?c=${m.source_conversation_id}` : null;
  const title = m.source_title || common("untitled");

  if (titleFirst) {
    return (
      <p className="flex flex-wrap items-baseline gap-x-2 text-sm font-[550]">
        {href ? (
          <Link href={href} className="underline-offset-2 hover:underline">
            {title}
          </Link>
        ) : (
          <span>{title}</span>
        )}
        {date}
      </p>
    );
  }
  return (
    <p className="text-xs text-muted-foreground">
      {date}
      {href && (
        <>
          {" · "}
          <Link href={href} className="text-primary underline-offset-2 hover:underline">
            {common("from", { title })}
          </Link>
        </>
      )}
    </p>
  );
}
