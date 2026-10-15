"use client";

import { ArrowLeft, BookOpenText, Maximize2, Minimize2, PenLine, Trash2, X } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { ErrorText } from "@/components/ui/error-text";
import { Select } from "@/components/ui/select";
import { type ApiErrorLike, useErrorMessage } from "@/i18n/errors";
import { cn } from "@/lib/utils";
import type { WorkspaceDoc, WorkspaceDocDetail, WorkspaceKind, WorkspaceLayout } from "@/lib/workspace";

import { ReadingView } from "./reading-view";
import { SelectionAsk } from "./selection-ask";
import { WritingView } from "./writing-view";

const KIND_ICONS: Record<WorkspaceKind, typeof BookOpenText> = {
  reading: BookOpenText,
  writing: PenLine,
};

type Props = {
  layout: WorkspaceLayout;
  /** The conversation's documents, for switching between them. */
  docs: WorkspaceDoc[];
  docId: string;
  doc: WorkspaceDocDetail | null;
  error: ApiErrorLike | null;
  /** Split layout only: the chat column is hidden. */
  fullscreen: boolean;
  onFullscreen: (on: boolean) => void;
  onSwitch: (docId: string) => void;
  onClose: () => void;
  onDelete: () => void;
  /** Selected text → a quote in the input box. */
  onAsk: (text: string) => void;
  /** A save, a decision or a revert changed the document. */
  onDoc: (doc: WorkspaceDocDetail) => void;
  /** Goes up when the tutor proposes changes in the chat. */
  editsSignal: number;
  className?: string;
};

/**
 * The workspace beside the chat (ADR 0043 §2): which document, its version, fullscreen,
 * close, then the document itself.
 */
export function WorkspacePane({
  layout,
  docs,
  docId,
  doc,
  error,
  fullscreen,
  onFullscreen,
  onSwitch,
  onClose,
  onDelete,
  onAsk,
  onDoc,
  editsSignal,
  className,
}: Props) {
  const t = useTranslations("chat.workspace");
  const errorMessage = useErrorMessage();
  const listed = docs.find((d) => d.id === docId);
  const title = doc?.title ?? listed?.title ?? "";
  const Icon = KIND_ICONS[doc?.kind ?? listed?.kind ?? "reading"];

  return (
    <section
      aria-label={t("label")}
      data-testid="workspace"
      data-layout={layout}
      className={cn("flex min-h-0 min-w-0 flex-col bg-background", className)}
    >
      <header className="flex h-14 shrink-0 items-center gap-1 border-b px-2 md:h-12 md:px-3">
        {layout === "overlay" && (
          <Button variant="ghost" size="sm" onClick={onClose}>
            <ArrowLeft />
            {t("backToChat")}
          </Button>
        )}
        <Icon aria-hidden className="ml-1 size-4 shrink-0 text-muted-foreground" />
        {docs.length > 1 ? (
          <Select
            aria-label={t("switch")}
            className="h-8 max-w-[min(100%,22rem)] min-w-0 flex-1 border-0 bg-transparent px-1.5 text-[14px] font-semibold shadow-none"
            value={docId}
            onValueChange={onSwitch}
            options={docs.map((d) => ({ value: d.id, label: d.title || t("untitled") }))}
          />
        ) : (
          <h2 className="min-w-0 truncate px-1.5 text-[14px] font-semibold">{title || t("untitled")}</h2>
        )}
        {doc && (
          <span className="shrink-0 text-xs text-muted-foreground" data-testid="workspace-version">
            {t("version", { n: doc.version })}
          </span>
        )}
        <span className="flex-1" />
        {layout === "split" && (
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label={fullscreen ? t("exitFullscreen") : t("fullscreen")}
            title={fullscreen ? t("exitFullscreen") : t("fullscreen")}
            aria-pressed={fullscreen}
            onClick={() => onFullscreen(!fullscreen)}
          >
            {fullscreen ? <Minimize2 /> : <Maximize2 />}
          </Button>
        )}
        <ConfirmDialog
          trigger={
            <Button variant="ghost" size="icon-sm" aria-label={t("delete")} title={t("delete")}>
              <Trash2 />
            </Button>
          }
          title={t("confirmDelete")}
          description={t("confirmDeleteDetail")}
          onConfirm={onDelete}
        />
        {layout !== "overlay" && (
          <Button variant="ghost" size="icon-sm" aria-label={t("close")} title={t("close")} onClick={onClose}>
            <X />
          </Button>
        )}
      </header>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {error ? (
          <ErrorText className="p-6">{errorMessage(error)}</ErrorText>
        ) : doc ? (
          <SelectionAsk onAsk={onAsk} className="mx-auto max-w-3xl px-5 py-6 md:px-8">
            {doc.truncated && (
              <p className="mb-4 text-xs text-muted-foreground">{t("truncated")}</p>
            )}
            {doc.kind === "reading" ? (
              <ReadingView doc={doc} />
            ) : (
              <WritingView key={doc.id} doc={doc} onDoc={onDoc} editsSignal={editsSignal} />
            )}
          </SelectionAsk>
        ) : (
          <p className="p-6 text-sm text-muted-foreground" role="status">
            {t("loading")}
          </p>
        )}
      </div>
    </section>
  );
}
