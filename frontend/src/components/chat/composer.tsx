"use client";

import { useTranslations } from "next-intl";
import { type FormEvent, type KeyboardEvent, useState } from "react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";

const MAX_LENGTH = 4000; // backend MessageIn limit

type Props = {
  streaming: boolean;
  disabled?: boolean;
  onSend: (text: string) => Promise<boolean>;
  onStop: () => void;
};

export function Composer({ streaming, disabled, onSend, onStop }: Props) {
  const t = useTranslations("chat");
  const [text, setText] = useState("");

  async function submit(event?: FormEvent) {
    event?.preventDefault();
    const content = text.trim();
    if (!content || streaming) return;
    setText("");
    // Put the text back if nothing was sent (e.g. no model configured yet).
    if (!(await onSend(content))) setText(content);
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      void submit();
    }
  }

  return (
    <form onSubmit={submit} className="mx-auto flex w-full max-w-3xl items-end gap-2 p-4">
      <Textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={onKeyDown}
        placeholder={t("placeholder")}
        aria-label={t("placeholder")}
        maxLength={MAX_LENGTH}
        rows={2}
        disabled={disabled}
        className="max-h-48 min-h-12 resize-none"
      />
      {streaming ? (
        <Button type="button" variant="outline" onClick={onStop}>
          {t("stop")}
        </Button>
      ) : (
        <Button type="submit" disabled={disabled || !text.trim()}>
          {t("send")}
        </Button>
      )}
    </form>
  );
}
