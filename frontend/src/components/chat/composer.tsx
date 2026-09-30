"use client";

import { Mic, Paperclip, Square } from "lucide-react";
import { useTranslations } from "next-intl";
import {
  type ClipboardEvent,
  type FormEvent,
  type KeyboardEvent,
  useRef,
  useState,
} from "react";

import { AiBadge } from "@/components/ai-badge";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { ACCEPT } from "@/lib/attachments";
import type { Attachment } from "@/lib/types";

import { AttachmentTrayView } from "./attachment-tray";
import type { AttachmentTray } from "./use-attachments";
import { MAX_RECORDING_SECONDS, useRecorder } from "./use-recorder";

const MAX_LENGTH = 4000; // backend MessageIn limit

type Props = {
  streaming: boolean;
  disabled?: boolean;
  tray: AttachmentTray;
  onSend: (text: string, attachments: Attachment[]) => Promise<boolean>;
  onStop: () => void;
};

const clock = (seconds: number) =>
  `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;

export function Composer({ streaming, disabled, tray, onSend, onStop }: Props) {
  const t = useTranslations("chat");
  const [text, setText] = useState("");
  const fileInput = useRef<HTMLInputElement>(null);
  const recorder = useRecorder((file) => tray.add([file]));

  const empty = !text.trim() && tray.items.length === 0;
  const blocked = streaming || disabled || tray.pending || recorder.recording;

  async function submit(event?: FormEvent) {
    event?.preventDefault();
    if (empty || blocked) return;
    const content = text.trim();
    setText("");
    const taken = tray.take();
    const sent = await onSend(
      content,
      taken.flatMap((i) => (i.attachment ? [i.attachment] : [])),
    );
    // Put everything back if nothing was sent (e.g. no model configured yet).
    if (sent) {
      tray.release(taken);
    } else {
      setText(content);
      tray.restore(taken);
    }
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      void submit();
    }
  }

  function onPaste(event: ClipboardEvent<HTMLTextAreaElement>) {
    const files = Array.from(event.clipboardData.files);
    if (files.length === 0) return; // plain text: let it paste
    event.preventDefault();
    tray.add(files);
  }

  return (
    <form onSubmit={submit} className="mx-auto flex w-full max-w-3xl flex-col gap-2 p-4">
      <AttachmentTrayView tray={tray} />
      {recorder.error && (
        <p role="alert" className="text-xs text-destructive">
          {t(`attachments.${recorder.error}`)}
        </p>
      )}
      <div className="flex items-end gap-2">
        <input
          ref={fileInput}
          type="file"
          accept={ACCEPT}
          multiple
          hidden
          data-testid="attachment-input"
          onChange={(e) => {
            tray.add(Array.from(e.target.files ?? []));
            e.target.value = ""; // picking the same file again still fires change
          }}
        />
        <div className="flex flex-col gap-1">
          <div className="relative">
            <Button
              type="button"
              size="icon"
              variant="ghost"
              aria-label={t("attachments.attach")}
              title={t("attachments.attach")}
              disabled={disabled || recorder.recording}
              onClick={() => fileInput.current?.click()}
            >
              <Paperclip />
            </Button>
            <AiBadge feature={["chat_image", "chat_pdf"]} className="absolute -top-1.5 -right-1.5" />
          </div>
          {recorder.recording ? (
            <Button
              type="button"
              size="icon"
              variant="destructive"
              aria-label={t("attachments.stopRecording")}
              title={t("attachments.stopRecording")}
              onClick={recorder.stop}
            >
              <Square />
            </Button>
          ) : (
            <div className="relative">
              <Button
                type="button"
                size="icon"
                variant="ghost"
                aria-label={t("attachments.record")}
                title={t("attachments.record")}
                disabled={disabled}
                onClick={() => void recorder.start()}
              >
                <Mic />
              </Button>
              <AiBadge feature="chat_audio" className="absolute -top-1.5 -right-1.5" />
            </div>
          )}
        </div>
        {recorder.recording ? (
          <div
            role="status"
            className="flex min-h-12 flex-1 items-center gap-3 rounded-md border px-3 text-sm"
          >
            <span className="size-2 animate-pulse rounded-full bg-destructive" />
            <span className="font-mono">
              {clock(recorder.seconds)} / {clock(MAX_RECORDING_SECONDS)}
            </span>
            <span
              aria-hidden
              data-testid="recording-level"
              className="h-1.5 w-16 overflow-hidden rounded-full bg-muted"
            >
              <span
                className="block h-full rounded-full bg-primary transition-[width] duration-75"
                style={{ width: `${Math.round(recorder.level * 100)}%` }}
              />
            </span>
            <span className="text-muted-foreground">{t("attachments.recording")}</span>
            <Button
              type="button"
              size="sm"
              variant="ghost"
              className="ml-auto"
              onClick={recorder.cancel}
            >
              {t("attachments.discardRecording")}
            </Button>
          </div>
        ) : (
          <Textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={onKeyDown}
            onPaste={onPaste}
            placeholder={t("placeholder")}
            aria-label={t("placeholder")}
            maxLength={MAX_LENGTH}
            rows={2}
            disabled={disabled}
            className="max-h-48 min-h-12 resize-none"
          />
        )}
        {streaming ? (
          <Button type="button" variant="outline" onClick={onStop}>
            {t("stop")}
          </Button>
        ) : (
          <div className="relative">
            <Button type="submit" disabled={empty || blocked}>
              {t("send")}
            </Button>
            <AiBadge feature="chat_message" className="absolute -top-1.5 -right-1.5" />
          </div>
        )}
      </div>
      {tray.pending && !streaming && (
        <p className="text-xs text-muted-foreground">{t("attachments.waitToSend")}</p>
      )}
    </form>
  );
}
