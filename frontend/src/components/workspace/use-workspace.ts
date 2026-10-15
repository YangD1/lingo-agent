"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import type { ApiErrorLike } from "@/i18n/errors";
import { ApiError } from "@/lib/api";
import { getDoc, listDocs, type WorkspaceDoc, type WorkspaceDocDetail } from "@/lib/workspace";

const toApiErrorLike = (error: unknown): ApiErrorLike =>
  error instanceof ApiError ? error : { code: "network_error", message: String(error) };

/** What was loaded, and for which conversation or document: a switch starts empty. */
type Owned<T> = { key: string | null; value: T };

/**
 * A conversation's workspace documents (oldest first) and the one open beside the chat
 * (ADR 0043 §3). `reload` after creating, deleting or the tutor opening one.
 */
export function useWorkspace(conversationId: string | null, docId: string | null) {
  const [docs, setDocs] = useState<Owned<WorkspaceDoc[]>>({ key: conversationId, value: [] });
  const [detail, setDetail] = useState<
    Owned<{ doc: WorkspaceDocDetail | null; error: ApiErrorLike | null }>
  >({ key: null, value: { doc: null, error: null } });
  const current = useRef(conversationId);
  useEffect(() => {
    current.current = conversationId;
  });

  const reload = useCallback(() => {
    const id = current.current;
    if (id === null) return;
    listDocs(id).then(
      (value) => current.current === id && setDocs({ key: id, value }),
      () => {},
    );
  }, []);
  useEffect(reload, [conversationId, reload]);

  const [version, setVersion] = useState(0);
  /** Fetch the open document again (it was saved, or a version was taken). */
  const refresh = useCallback(() => setVersion((v) => v + 1), []);
  useEffect(() => {
    if (docId === null) return;
    let cancelled = false;
    getDoc(docId).then(
      (doc) => !cancelled && setDetail({ key: docId, value: { doc, error: null } }),
      (e: unknown) =>
        !cancelled && setDetail({ key: docId, value: { doc: null, error: toApiErrorLike(e) } }),
    );
    return () => {
      cancelled = true;
    };
  }, [docId, version]);

  /** The open document as a save, a decision or a revert returned it. */
  const replace = useCallback(
    (doc: WorkspaceDocDetail) => setDetail({ key: doc.id, value: { doc, error: null } }),
    [],
  );

  const mine = detail.key === docId ? detail.value : { doc: null, error: null };
  return {
    docs: docs.key === conversationId ? docs.value : [],
    doc: mine.doc,
    error: mine.error,
    loading: docId !== null && detail.key !== docId,
    reload,
    refresh,
    replace,
  };
}
