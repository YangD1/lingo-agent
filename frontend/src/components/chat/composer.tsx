"use client";

import { ArrowUp, Mic, Paperclip, Square } from "lucide-react";
import { useTranslations } from "next-intl";
import {
  type ClipboardEvent,
  type FormEvent,
  type KeyboardEvent,
  type ReactNode,
  useRef,
  useState,
} from "react";

import { AiBadge } from "@/components/ai-badge";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { ErrorText } from "@/components/ui/error-text";
import { ACCEPT } from "@/lib/attachments";
import type { Attachment } from "@/lib/types";
import { cn } from "@/lib/utils";

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
  /** Above the input row: the language switch. */
  toolbar?: ReactNode;
};

const clock = (seconds: number) =>
  `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;

export function Composer({ streaming, disabled, tray, onSend, onStop, toolbar }: Props) {
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
    <form onSubmit={submit} className="w-full px-2.5 pt-1.5 pb-3 md:px-8 md:pt-2 md:pb-5">
      <div className="mx-auto flex max-w-3xl flex-col gap-2">
        {toolbar}
        <div className="flex flex-col rounded-[18px] border border-input bg-card shadow-(--shadow-lift) transition-[border-color,box-shadow] focus-within:border-ring focus-within:ring-3 focus-within:ring-ring/20">
          <div className="px-2.5 pt-2.5 empty:hidden">
            <AttachmentTrayView tray={tray} />
          </div>
          <div className="flex items-end gap-1 p-2">
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
            <div className="flex flex-col gap-0.5">
              <div className="flex items-center gap-0.5">
                <Button
                  type="button"
                  size="icon-sm"
                  variant="ghost"
                  className="text-muted-foreground hover:text-foreground"
                  aria-label={t("attachments.attach")}
                  title={t("attachments.attach")}
                  disabled={disabled || recorder.recording}
                  onClick={() => fileInput.current?.click()}
                >
                  <Paperclip />
                </Button>
                <AiBadge feature={["chat_image", "chat_pdf"]} />
              </div>
              {recorder.recording ? (
                <Button
                  type="button"
                  size="icon-sm"
                  variant="destructive"
                  className="bg-destructive text-white hover:bg-destructive/90"
                  aria-label={t("attachments.stopRecording")}
                  title={t("attachments.stopRecording")}
                  onClick={recorder.stop}
                >
                  <Square className="fill-current" />
                </Button>
              ) : (
                <div className="flex items-center gap-0.5">
                  <Button
                    type="button"
                    size="icon-sm"
                    variant="ghost"
                    className="text-muted-foreground hover:text-foreground"
                    aria-label={t("attachments.record")}
                    title={t("attachments.record")}
                    disabled={disabled}
                    onClick={() => void recorder.start()}
                  >
                    <Mic />
                  </Button>
                  <AiBadge feature="chat_audio" />
                </div>
              )}
            </div>
            {recorder.recording ? (
              <div
                role="status"
                className="flex min-h-16 flex-1 flex-wrap items-center gap-x-3 gap-y-1 px-1.5 text-sm"
              >
                <span className="size-2.5 shrink-0 animate-pulse rounded-full bg-destructive ring-4 ring-destructive/20" />
                <span className="font-mono text-[13px] tabular-nums">
                  {clock(recorder.seconds)} / {clock(MAX_RECORDING_SECONDS)}
                </span>
                <LevelMeter level={recorder.level} />
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
                className="max-h-48 min-h-16 flex-1 resize-none rounded-none border-0 bg-transparent px-1.5 py-1.5 text-[15px] shadow-none focus-visible:border-0 focus-visible:ring-0 dark:bg-transparent"
              />
            )}
            {streaming ? (
              <Button type="button" variant="outline" onClick={onStop}>
                <Square className="size-3 fill-current" />
                {t("stop")}
              </Button>
            ) : (
              <div className="relative">
                <Button type="submit" disabled={empty || blocked}>
                  <ArrowUp />
                  {t("send")}
                </Button>
                <AiBadge feature="chat_message" corner />
              </div>
            )}
          </div>
        </div>
        {recorder.error && (
          <ErrorText size="xs" className="px-1">{t(`attachments.${recorder.error}`)}</ErrorText>
        )}
        {tray.pending && !streaming && (
          <p className="px-1 text-xs text-muted-foreground">{t("attachments.waitToSend")}</p>
        )}
      </div>
    </form>
  );
}

const METER_BARS = 12;

/** The microphone level as a row of thin bars, lit from the left. */
function LevelMeter({ level }: { level: number }) {
  const lit = Math.round(level * METER_BARS);
  return (
    <span
      aria-hidden
      data-testid="recording-level"
      data-level={Math.round(level * 100)}
      className="flex h-4 items-center gap-[2px]"
    >
      {Array.from({ length: METER_BARS }, (_, i) => (
        <span
          key={i}
          className={cn(
            "w-[3px] rounded-full transition-colors duration-75",
            i < lit ? "bg-destructive" : "bg-muted",
          )}
          style={{ height: `${40 + ((i * 37) % 60)}%` }}
        />
      ))}
    </span>
  );
}
