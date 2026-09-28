"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import type { ApiErrorLike } from "@/i18n/errors";
import { ApiError } from "@/lib/api";
import {
  compressImage,
  deleteAttachment,
  getAttachment,
  guessKind,
  MAX_IMAGES_PER_MESSAGE,
  MAX_PER_MESSAGE,
  retryAttachment,
  updateAttachmentText,
  uploadAttachment,
} from "@/lib/attachments";
import type { Attachment, AttachmentKind } from "@/lib/types";

/** How often a file being read or transcribed is checked (ADR 0008 §3: polling, not push). */
export const POLL_MS = 1000;

/** A file in the composer, from picking it until the message carrying it is sent. */
export type PendingAttachment = {
  key: string;
  kind: AttachmentKind;
  filename: string;
  /** The picked file, kept so a failed upload can be tried again. */
  file: File;
  /** Local preview of an image while (and after) it uploads. */
  previewUrl: string | null;
  /** The backend's record; null while uploading or if the upload failed. */
  attachment: Attachment | null;
  /** Why the upload (not the processing) failed. */
  error: ApiErrorLike | null;
};

export type TrayProblem = "too_many_attachments" | "too_many_images";

const toError = (e: unknown): ApiErrorLike =>
  e instanceof ApiError ? e : { code: "network_error", message: String(e) };

let keySeq = 0;
const nextKey = () => `a${++keySeq}`;

const revoke = (items: PendingAttachment[]) =>
  items.forEach((i) => i.previewUrl && URL.revokeObjectURL(i.previewUrl));

/** True while the item still needs to reach `ready` before the message can go. */
export const isPending = (item: PendingAttachment) =>
  item.error !== null || item.attachment?.status !== "ready";

/**
 * The composer's attachments for `conversationId`. Uploading needs a conversation, so
 * the first file in a new chat creates one through `ensureConversation` (ADR 0008 §3).
 * Switching to another conversation drops the tray (the files stay on the server
 * unsent and are cleaned up after 24 hours).
 */
export function useAttachments(
  conversationId: string | null,
  ensureConversation: () => Promise<string>,
) {
  const [items, setItems] = useState<PendingAttachment[]>([]);
  const [problem, setProblem] = useState<TrayProblem | null>(null);
  const itemsRef = useRef(items);
  useEffect(() => {
    itemsRef.current = items;
  });

  // The conversation the tray belongs to. While the first upload is creating it, the
  // switch to the new id is ours and must not clear the tray.
  const ownerRef = useRef(conversationId);
  const creatingRef = useRef(false);
  useEffect(() => {
    if (conversationId === ownerRef.current) return;
    const adopt = creatingRef.current;
    ownerRef.current = conversationId;
    if (adopt) return;
    setItems((all) => {
      revoke(all);
      return [];
    });
    setProblem(null);
  }, [conversationId]);

  useEffect(() => () => revoke(itemsRef.current), []);

  const patch = (key: string, change: Partial<PendingAttachment>) =>
    setItems((all) => all.map((i) => (i.key === key ? { ...i, ...change } : i)));

  const upload = useCallback(
    async (item: PendingAttachment) => {
      patch(item.key, { error: null, attachment: null });
      try {
        let id = ownerRef.current;
        if (id === null) {
          creatingRef.current = true;
          try {
            id = await ensureConversation();
          } finally {
            creatingRef.current = false;
          }
          ownerRef.current = id;
        }
        const file = item.kind === "image" ? await compressImage(item.file) : item.file;
        patch(item.key, { attachment: await uploadAttachment(id, file) });
      } catch (e) {
        patch(item.key, { error: toError(e) });
      }
    },
    [ensureConversation],
  );

  const add = useCallback(
    (files: File[]) => {
      if (files.length === 0) return;
      const current = itemsRef.current;
      let images = current.filter((i) => i.kind === "image").length;
      const accepted: PendingAttachment[] = [];
      let refused: TrayProblem | null = null;
      for (const file of files) {
        const kind = guessKind(file);
        if (current.length + accepted.length >= MAX_PER_MESSAGE) {
          refused = "too_many_attachments";
          break;
        }
        if (kind === "image" && images >= MAX_IMAGES_PER_MESSAGE) {
          refused = "too_many_images";
          continue;
        }
        if (kind === "image") images++;
        accepted.push({
          key: nextKey(),
          kind,
          filename: file.name,
          file,
          previewUrl: kind === "image" ? URL.createObjectURL(file) : null,
          attachment: null,
          error: null,
        });
      }
      setProblem(refused);
      if (accepted.length === 0) return;
      setItems((all) => [...all, ...accepted]);
      // One after another: the first may be creating the conversation the rest go to.
      void accepted.reduce((previous, item) => previous.then(() => upload(item)), Promise.resolve());
    },
    [upload],
  );

  const remove = useCallback((key: string) => {
    const item = itemsRef.current.find((i) => i.key === key);
    if (!item) return;
    revoke([item]);
    setItems((all) => all.filter((i) => i.key !== key));
    setProblem(null);
    if (item.attachment) void deleteAttachment(item.attachment.id).catch(() => {});
  }, []);

  /** Upload again, or process again if the backend failed to read the file. */
  const retry = useCallback(
    async (key: string) => {
      const item = itemsRef.current.find((i) => i.key === key);
      if (!item) return;
      if (!item.attachment) return upload(item);
      try {
        patch(key, { attachment: await retryAttachment(item.attachment.id), error: null });
      } catch (e) {
        patch(key, { error: toError(e) });
      }
    },
    [upload],
  );

  /** Correct an image reading or a transcript; throws so the editor can show why. */
  const saveText = useCallback(async (key: string, text: string) => {
    const item = itemsRef.current.find((i) => i.key === key);
    if (!item?.attachment) return;
    patch(key, { attachment: await updateAttachmentText(item.attachment.id, text) });
  }, []);

  /** Hand the tray's files to a message being sent; `restore` them if it was refused. */
  const take = useCallback((): PendingAttachment[] => {
    const taken = itemsRef.current;
    itemsRef.current = [];
    setItems([]);
    setProblem(null);
    return taken;
  }, []);
  const restore = useCallback((taken: PendingAttachment[]) => {
    setItems((all) => [...taken, ...all]);
  }, []);
  const release = useCallback((taken: PendingAttachment[]) => revoke(taken), []);

  // Poll whatever the backend is still reading or transcribing.
  const processing = items.some((i) => i.attachment?.status === "processing");
  useEffect(() => {
    if (!processing) return;
    const timer = window.setInterval(() => {
      for (const item of itemsRef.current) {
        if (item.attachment?.status !== "processing") continue;
        getAttachment(item.attachment.id).then(
          (attachment) => patch(item.key, { attachment }),
          () => {}, // try again on the next tick
        );
      }
    }, POLL_MS);
    return () => window.clearInterval(timer);
  }, [processing]);

  return {
    items,
    problem,
    /** Something is still uploading, being processed, or failed. */
    pending: items.some(isPending),
    add,
    remove,
    retry,
    saveText,
    take,
    restore,
    release,
  };
}

export type AttachmentTray = ReturnType<typeof useAttachments>;
