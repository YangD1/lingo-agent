import { api, apiFetch } from "./api";
import type { Attachment, AttachmentKind } from "./types";

/** What the file picker offers; the backend decides by the file's bytes, not this (ADR 0008 §3). */
export const ACCEPT =
  "image/png,image/jpeg,image/gif,image/webp,audio/*,application/pdf,.docx,.txt,.md";

// Per message (backend attachments/service.py).
export const MAX_PER_MESSAGE = 5;
export const MAX_IMAGES_PER_MESSAGE = 4;

/** Long edge the backend keeps images at, so sending more is wasted upload. */
export const MAX_IMAGE_EDGE = 1600;
const JPEG_QUALITY = 0.85;

export const contentUrl = (attachment: Pick<Attachment, "id">) =>
  `/api/attachments/${attachment.id}/content`;

/** A guess for showing the file before the backend has looked at it. */
export function guessKind(file: Pick<File, "type">): AttachmentKind {
  if (file.type.startsWith("image/")) return "image";
  if (file.type.startsWith("audio/")) return "audio";
  return "document";
}

export async function uploadAttachment(conversationId: string, file: File): Promise<Attachment> {
  const form = new FormData();
  form.append("file", file);
  const response = await apiFetch(`/conversations/${conversationId}/attachments`, {
    method: "POST",
    body: form,
  });
  return (await response.json()) as Attachment;
}

export const getAttachment = (id: string) => api<Attachment>(`/attachments/${id}`);

export const updateAttachmentText = (id: string, text: string) =>
  api<Attachment>(`/attachments/${id}`, { method: "PATCH", json: { text } });

export const retryAttachment = (id: string) =>
  api<Attachment>(`/attachments/${id}/retry`, { method: "POST" });

export const deleteAttachment = (id: string) =>
  api<void>(`/attachments/${id}`, { method: "DELETE" });

/** Scale (width, height) down so the long edge is at most `max`; never scales up. */
export function fitWithin(
  width: number,
  height: number,
  max = MAX_IMAGE_EDGE,
): { width: number; height: number } {
  const scale = Math.min(1, max / Math.max(width, height));
  return { width: Math.round(width * scale), height: Math.round(height * scale) };
}

/**
 * Re-encode a photo as a JPEG no larger than the backend keeps (ADR 0008 §3): a phone
 * photo goes from several MB to a few hundred KB, and the canvas drops EXIF (GPS etc.).
 * GIFs and anything the browser can't decode (e.g. HEIC on most browsers) go as they
 * are; the backend then accepts or refuses them.
 */
export async function compressImage(file: File): Promise<File> {
  if (!file.type.startsWith("image/") || file.type === "image/gif") return file;
  try {
    const bitmap = await createImageBitmap(file, { imageOrientation: "from-image" });
    const { width, height } = fitWithin(bitmap.width, bitmap.height);
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const context = canvas.getContext("2d");
    if (!context) return file;
    context.fillStyle = "#fff"; // JPEG has no transparency
    context.fillRect(0, 0, width, height);
    context.drawImage(bitmap, 0, 0, width, height);
    bitmap.close();
    const blob = await new Promise<Blob | null>((resolve) =>
      canvas.toBlob(resolve, "image/jpeg", JPEG_QUALITY),
    );
    if (!blob) return file;
    const name = file.name.replace(/\.[^./]*$/, "") || "image";
    return new File([blob], `${name}.jpg`, { type: "image/jpeg" });
  } catch {
    return file;
  }
}
