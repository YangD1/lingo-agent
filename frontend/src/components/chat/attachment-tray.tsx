"use client";

import { AudioLines, FileText, Loader2, Pencil, RotateCw, X } from "lucide-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { ErrorText } from "@/components/ui/error-text";
import { type ApiErrorLike, useErrorMessage } from "@/i18n/errors";
import { contentUrl } from "@/lib/attachments";
import type { AttachmentKind } from "@/lib/types";
import { cn } from "@/lib/utils";

import type { AttachmentTray, PendingAttachment } from "./use-attachments";

/** Failures that mean "set up a model in Settings" rather than "try again". */
export const SETTINGS_ERRORS = new Set([
  "no_llm_configured",
  "no_vision_model",
  "no_asr_model",
  "models_disabled",
]);

// Readings and transcripts can be corrected before sending; documents are shown as is.
const EDITABLE: ReadonlySet<AttachmentKind> = new Set(["image", "audio"]);

function Thumb({ item }: { item: PendingAttachment }) {
  const src =
    item.previewUrl ?? (item.kind === "image" && item.attachment ? contentUrl(item.attachment) : null);
  if (src) {
    // eslint-disable-next-line @next/next/no-img-element -- blob: and authenticated URLs
    return <img src={src} alt="" className="size-9 shrink-0 rounded-[7px] object-cover" />;
  }
  const Icon = item.kind === "audio" ? AudioLines : FileText;
  return (
    <span className="flex size-9 shrink-0 items-center justify-center rounded-[7px] bg-muted">
      <Icon className="size-5 text-muted-foreground" />
    </span>
  );
}

function Status({ item }: { item: PendingAttachment }) {
  const t = useTranslations("chat.attachments");
  const errorMessage = useErrorMessage();
  const failure: ApiErrorLike | null =
    item.error ??
    (item.attachment?.status === "failed"
      ? {
          code: item.attachment.error ?? "processing_failed",
          message: item.attachment.meta.error_message ?? "",
        }
      : null);
  if (failure) {
    return (
      <span className="text-destructive">
        {errorMessage(failure)}
        {SETTINGS_ERRORS.has(failure.code) && (
          <>
            {" "}
            <Link href="/settings" className="underline">
              {t("setUp")}
            </Link>
          </>
        )}
      </span>
    );
  }
  const attachment = item.attachment;
  if (!attachment) return <span>{t("uploading")}</span>;
  if (attachment.status === "ready") return <span>{t(`ready.${attachment.kind}`)}</span>;
  const progress = attachment.meta.progress;
  return (
    <span>
      {t(`processing.${attachment.kind}`)}
      {progress && progress.total > 1 && ` ${t("progress", progress)}`}
    </span>
  );
}

function TextEditor({
  item,
  onSave,
  onClose,
}: {
  item: PendingAttachment;
  onSave: (text: string) => Promise<void>;
  onClose: () => void;
}) {
  const t = useTranslations("chat.attachments");
  const errorMessage = useErrorMessage();
  const [text, setText] = useState(item.attachment?.text ?? "");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function save() {
    setSaving(true);
    setError(null);
    try {
      await onSave(text.trim());
      onClose();
    } catch (e) {
      setError(errorMessage(e as ApiErrorLike));
    } finally {
      setSaving(false);
    }
  }

  const label = t(item.kind === "audio" ? "transcriptLabel" : "readingLabel", {
    name: item.filename,
  });
  return (
    <div className="flex flex-col gap-2 rounded-lg border p-3">
      <p className="text-sm font-medium">{label}</p>
      <p className="text-xs text-muted-foreground">{t("editHint")}</p>
      <Textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        aria-label={label}
        rows={6}
        className="max-h-72"
      />
      {error && (
        <ErrorText>{error}</ErrorText>
      )}
      <div className="flex gap-2">
        <Button size="sm" onClick={save} disabled={saving || !text.trim()}>
          {t("save")}
        </Button>
        <Button size="sm" variant="ghost" onClick={onClose}>
          {t("cancel")}
        </Button>
      </div>
    </div>
  );
}

export function AttachmentTrayView({ tray }: { tray: AttachmentTray }) {
  const t = useTranslations("chat.attachments");
  const [editing, setEditing] = useState<string | null>(null);
  const editingItem = tray.items.find((i) => i.key === editing && i.attachment?.status === "ready");

  if (tray.items.length === 0 && !tray.problem) return null;
  return (
    <div className="flex flex-col gap-2">
      <ul className="flex flex-wrap gap-2" aria-label={t("label")}>
        {tray.items.map((item) => {
          const busy = !item.error && item.attachment?.status !== "ready" && item.attachment?.status !== "failed";
          const failed = item.error !== null || item.attachment?.status === "failed";
          return (
            <li
              key={item.key}
              data-status={item.error ? "upload_failed" : (item.attachment?.status ?? "uploading")}
              className={cn(
                "flex w-full items-center gap-2 rounded-lg border bg-background p-1.5 pr-1 text-xs sm:w-[236px]",
                failed && "border-destructive/50",
              )}
            >
              <Thumb item={item} />
              <div className="min-w-0 flex-1">
                <p className="truncate font-medium" title={item.filename}>
                  {item.filename}
                </p>
                <p className="flex items-center gap-1 text-muted-foreground">
                  {busy && <Loader2 className="size-3 shrink-0 animate-spin" />}
                  <Status item={item} />
                </p>
              </div>
              {failed && (
                <Button
                  size="icon-xs"
                  variant="ghost"
                  aria-label={t("retry", { name: item.filename })}
                  onClick={() => void tray.retry(item.key)}
                >
                  <RotateCw />
                </Button>
              )}
              {item.attachment?.status === "ready" && EDITABLE.has(item.kind) && (
                <Button
                  size="icon-xs"
                  variant="ghost"
                  aria-label={t("edit", { name: item.filename })}
                  aria-pressed={editing === item.key}
                  onClick={() => setEditing(editing === item.key ? null : item.key)}
                >
                  <Pencil />
                </Button>
              )}
              <Button
                size="icon-xs"
                variant="ghost"
                aria-label={t("remove", { name: item.filename })}
                onClick={() => tray.remove(item.key)}
              >
                <X />
              </Button>
            </li>
          );
        })}
      </ul>
      {tray.problem && (
        <ErrorText size="xs">{t(tray.problem)}</ErrorText>
      )}
      {editingItem && (
        <TextEditor
          key={editingItem.key}
          item={editingItem}
          onSave={(text) => tray.saveText(editingItem.key, text)}
          onClose={() => setEditing(null)}
        />
      )}
    </div>
  );
}
