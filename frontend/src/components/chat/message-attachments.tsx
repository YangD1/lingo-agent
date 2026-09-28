"use client";

import { Download, FileText } from "lucide-react";
import { useTranslations } from "next-intl";

import { contentUrl } from "@/lib/attachments";
import type { Attachment } from "@/lib/types";

const size = (bytes: number) =>
  bytes < 1024 * 1024 ? `${Math.max(1, Math.round(bytes / 1024))} KB` : `${(bytes / 1048576).toFixed(1)} MB`;

/** A sent message's files: image thumbnails, voice players and document cards (ADR 0008 §6). */
export function MessageAttachments({ attachments }: { attachments: Attachment[] }) {
  const t = useTranslations("chat.attachments");
  const images = attachments.filter((a) => a.kind === "image");
  const others = attachments.filter((a) => a.kind !== "image");
  return (
    <div className="mb-2 flex flex-col gap-2 last:mb-0">
      {images.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {images.map((a) => (
            <a
              key={a.id}
              href={contentUrl(a)}
              target="_blank"
              rel="noopener"
              title={t("openImage", { name: a.filename })}
            >
              {/* eslint-disable-next-line @next/next/no-img-element -- authenticated URL */}
              <img
                src={contentUrl(a)}
                alt={a.filename}
                loading="lazy"
                className="max-h-40 max-w-56 rounded-md bg-background object-cover"
              />
            </a>
          ))}
        </div>
      )}
      {others.map((a) =>
        a.kind === "audio" ? (
          // The transcript is the message text itself, so only the recording is shown.
          <audio
            key={a.id}
            controls
            preload="none"
            src={contentUrl(a)}
            aria-label={t("voiceMessage")}
            className="h-10 w-64 max-w-full"
          />
        ) : (
          <a
            key={a.id}
            href={contentUrl(a)}
            download={a.filename}
            className="flex w-64 max-w-full items-center gap-2 rounded-md bg-background p-2 text-xs text-foreground"
          >
            <FileText className="size-5 shrink-0 text-muted-foreground" />
            <span className="min-w-0 flex-1">
              <span className="block truncate font-medium">{a.filename}</span>
              <span className="text-muted-foreground">
                {size(a.size_bytes)}
                {a.meta.truncated ? ` · ${t("truncated")}` : ""}
              </span>
            </span>
            <Download className="size-4 shrink-0 text-muted-foreground" aria-label={t("download")} />
          </a>
        ),
      )}
    </div>
  );
}
