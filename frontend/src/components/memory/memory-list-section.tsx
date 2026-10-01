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
  const format = useFormatter();
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
            className="flex flex-col gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              void add();
            }}
          >
            <Textarea
              aria-label={t("addLabel")}
              placeholder={t("addPlaceholder")}
              value={draft}
              maxLength={MAX_LENGTH}
              onChange={(e) => setDraft(e.target.value)}
              className="min-h-10"
            />
            <div>
              <Button type="submit" size="sm" disabled={busy || !draft.trim()}>
                {t("add")}
              </Button>
            </div>
          </form>
        )}
        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}
        {memories && memories.length === 0 && (
          <p className="text-sm text-muted-foreground">{t("empty")}</p>
        )}
        {memories && memories.length > 0 && (
          <>
            <ul className="flex flex-col divide-y" aria-label={t("title")}>
              {memories.map((m) => (
                <li key={m.id} className="flex flex-col gap-1 py-2">
                  {editing?.id === m.id ? (
                    <form
                      className="flex flex-col gap-2"
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
                      />
                      <div className="flex gap-2">
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
                      <p className="flex-1 text-sm whitespace-pre-wrap">{m.content}</p>
                      {editable && (
                        <Button
                          size="icon-sm"
                          variant="ghost"
                          aria-label={common("edit")}
                          disabled={busy}
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
                            onClick={ask}
                          >
                            <Trash2 />
                          </Button>
                        )}
                      </InlineConfirm>
                    </div>
                  )}
                  <p className="text-xs text-muted-foreground">
                    {format.dateTime(new Date(m.updated_at), {
                      dateStyle: "medium",
                      timeStyle: "short",
                    })}
                    {m.source_conversation_id && (
                      <>
                        {" · "}
                        <Link
                          href={`/chat?c=${m.source_conversation_id}`}
                          className="underline-offset-2 hover:underline"
                        >
                          {common("from", { title: m.source_title || common("untitled") })}
                        </Link>
                      </>
                    )}
                  </p>
                </li>
              ))}
            </ul>
            <div>
              <ConfirmDialog
                trigger={
                  <Button size="sm" variant="outline" disabled={busy}>
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
