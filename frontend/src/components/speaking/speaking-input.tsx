"use client";

import { ArrowUp, Square } from "lucide-react";
import { useTranslations } from "next-intl";
import { type FormEvent, type KeyboardEvent, useState } from "react";

import { AiBadge } from "@/components/ai-badge";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import type { Attachment } from "@/lib/types";

// The backend's limit on a message.
const MAX_LENGTH = 4000;

/**
 * What the learner says in a speaking practice (task 59.3): typed here; spoken turns join
 * in task 59.4. `onSend` resolves false when nothing was sent, and the text stays.
 */
export function SpeakingInput({
  streaming,
  disabled,
  onSend,
  onStop,
}: {
  streaming: boolean;
  disabled: boolean;
  onSend: (text: string, attachments?: Attachment[]) => Promise<boolean>;
  onStop: () => void;
}) {
  const t = useTranslations("speaking.session");
  const [text, setText] = useState("");
  const empty = !text.trim();

  async function submit(event?: FormEvent) {
    event?.preventDefault();
    if (empty || streaming || disabled) return;
    const content = text.trim();
    setText("");
    if (!(await onSend(content))) setText(content);
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      void submit();
    }
  }

  return (
    <form onSubmit={submit} className="w-full px-2.5 pt-1.5 pb-3 md:px-8 md:pt-2 md:pb-5">
      <div className="mx-auto flex max-w-3xl items-end gap-2 rounded-[18px] border border-input bg-card p-2 shadow-(--shadow-lift) focus-within:border-ring focus-within:ring-3 focus-within:ring-ring/20">
        <Textarea
          lang="en"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder={t("placeholder")}
          aria-label={t("placeholder")}
          maxLength={MAX_LENGTH}
          rows={1}
          disabled={disabled}
          className="max-h-40 min-h-10 flex-1 resize-none rounded-none border-0 bg-transparent px-1.5 py-1.5 text-[15px] shadow-none focus-visible:border-0 focus-visible:ring-0 dark:bg-transparent"
        />
        {streaming ? (
          <Button type="button" variant="outline" onClick={onStop}>
            <Square className="size-3 fill-current" />
            {t("stop")}
          </Button>
        ) : (
          <div className="relative">
            <Button type="submit" disabled={empty || disabled}>
              <ArrowUp />
              {t("send")}
            </Button>
            <AiBadge feature="speaking_turn" corner />
          </div>
        )}
      </div>
    </form>
  );
}
