"use client";

import { Pencil, Trash2 } from "lucide-react";
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
import { api } from "@/lib/api";
import type { Memory, MemoryKind } from "@/lib/types";

const MAX_LENGTH = 1000; // backend/app/memory/service.py MAX_CONTENT_LENGTH

/**
 * Facts can be added and edited by the learner; conversation summaries are written by the
 * tutor and can only be deleted. Deleting is real deletion (ADR 0009).
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
    api<Memory[]>(`/memories?kind=${kind}`).then(setMemories, (e: unknown) =>
      setError(describe(e)),
    );
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
      setMemories((ms) => (ms ?? []).filter((m) => m.id !== memory.id));
    });

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
        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}
        {memories && memories.length === 0 && (
          <p className="rounded-lg border border-dashed px-4 py-6 text-center text-sm text-muted-foreground">
            {t("empty")}
          </p>
        )}
        {memories && memories.length > 0 && (
          <>
            <ul className="flex flex-col divide-y border-y" aria-label={t("title")}>
              {memories.map((m) => (
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
