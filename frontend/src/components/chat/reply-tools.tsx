"use client";

import { Languages, Settings2, Square, Volume2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { useCallback, useState } from "react";

import { AiBadge } from "@/components/ai-badge";
import { SpeechSettings } from "@/components/speech/speech-settings";
import { useDescribeError } from "@/components/settings/use-describe-error";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { api } from "@/lib/api";
import {
  speakSegments,
  speechSegments,
  stopSpeaking,
  useCanSpeak,
  useFellBack,
  useSpeaking,
} from "@/lib/speech";

export type TranslateTarget = "zh" | "en";

// Whether this page has already said the device has no Chinese voice.
let noChineseNoticed = false;

const HAN = /[㐀-䶿一-鿿豈-﫿]/g;
const LATIN = /[A-Za-z]/g;

/** Mostly English becomes Chinese, anything else English (Q24h). */
export function translationTarget(text: string): TranslateTarget {
  const latin = text.match(LATIN)?.length ?? 0;
  const han = text.match(HAN)?.length ?? 0;
  return latin > han ? "zh" : "en";
}

/** What a rendered message says, as it would be read: no code blocks, a break per block. */
export function readableText(markdown: Element): string {
  const copy = markdown.cloneNode(true) as Element;
  copy.querySelectorAll("pre").forEach((pre) => pre.remove());
  copy.querySelectorAll("p, li, h1, h2, h3, h4, h5, h6, td, th").forEach((el) => el.append("\n"));
  return copy.textContent ?? "";
}

type Translation = { text?: string; showing: boolean; busy: boolean; error?: string };

/**
 * Translations of the tutor's messages in one conversation (ADR 0017 §4), by message id.
 * Each is fetched once; switching back and forth after that makes no request.
 */
export function useReplyTranslations(conversationId: string | null) {
  const describe = useDescribeError();
  const [state, setState] = useState<{ for: string | null; byId: Record<string, Translation> }>({
    for: conversationId,
    byId: {},
  });
  const byId = state.for === conversationId ? state.byId : {};

  const patch = useCallback(
    (id: string, change: Partial<Translation>) =>
      setState((s) => {
        const current = s.for === conversationId ? s.byId : {};
        const before = current[id] ?? { showing: false, busy: false };
        return { for: conversationId, byId: { ...current, [id]: { ...before, ...change } } };
      }),
    [conversationId],
  );

  const toggle = async (id: string, target: TranslateTarget) => {
    const current = byId[id];
    if (current?.busy) return;
    if (current?.text !== undefined) return patch(id, { showing: !current.showing });
    if (!conversationId) return;
    patch(id, { busy: true, error: undefined });
    try {
      const { text } = await api<{ text: string }>(
        `/conversations/${conversationId}/messages/${encodeURIComponent(id)}/translate`,
        { method: "POST", json: { target } },
      );
      patch(id, { text, showing: true, busy: false });
    } catch (e) {
      patch(id, { busy: false, error: describe(e) });
    }
  };

  return { byId, toggle };
}

/**
 * Under a tutor message: read it aloud (browser voices, Chinese and English parts each in
 * their own) and switch between it and its translation.
 */
// The row under a tutor message (component-spec "对话页"): 28px buttons, muted until hovered.
const TOOL = "h-7 px-2 text-[12.5px] text-muted-foreground hover:text-foreground";
const ICON_TOOL = "size-7 text-muted-foreground hover:text-foreground";

export function ReplyTools({
  messageKey,
  messageId,
  content,
  translation,
  onTranslate,
}: {
  /** Identifies the message while it's read aloud. */
  messageKey: string;
  /** The backend's id; without one (not saved) there is nothing to translate. */
  messageId?: string;
  /** The original text, which decides the language to translate to. */
  content: string;
  translation?: Translation;
  onTranslate?: (id: string, target: TranslateTarget) => void;
}) {
  const t = useTranslations("chat.reply");
  const speakable = useCanSpeak();
  const speaking = useSpeaking(messageKey);
  const target = translationTarget(content);

  const [noChinese, setNoChinese] = useState(false);
  const fellBack = useFellBack(messageKey);

  const read = (button: HTMLElement) => {
    if (speaking) return stopSpeaking();
    const markdown = button.closest("li")?.querySelector('[data-slot="markdown"]');
    if (!markdown) return;
    const skipped = speakSegments(messageKey, speechSegments(readableText(markdown)));
    // Said once per page: the device won't grow a Chinese voice in between.
    if (skipped.includes("zh-CN") && !noChineseNoticed) {
      noChineseNoticed = true;
      setNoChinese(true);
    }
  };

  if (!speakable && !(messageId && onTranslate)) return null;
  return (
    <div className="mt-1.5 flex flex-wrap items-center gap-0.5 text-[12.5px] text-muted-foreground">
      {speakable && (
        <Button
          size="xs"
          variant="ghost"
          className={TOOL}
          aria-pressed={speaking}
          onClick={(e) => read(e.currentTarget)}
        >
          {speaking ? <Square /> : <Volume2 />}
          {speaking ? t("stop") : t("read")}
        </Button>
      )}
      {speakable && (
        <Popover>
          <PopoverTrigger
            render={<Button size="icon-xs" variant="ghost" className={ICON_TOOL} aria-label={t("readSettings")} />}
          >
            <Settings2 />
          </PopoverTrigger>
          <PopoverContent className="w-80" align="start">
            <SpeechSettings />
          </PopoverContent>
        </Popover>
      )}
      {messageId && onTranslate && (
        <>
          {speakable && <span aria-hidden className="mx-1 h-3.5 w-px bg-border" />}
          <Button
            size="xs"
            variant="ghost"
            className={TOOL}
            disabled={translation?.busy}
            aria-pressed={translation?.showing ?? false}
            onClick={() => onTranslate(messageId, target)}
            data-testid="reply-translate"
          >
            <Languages />
            {translation?.busy
              ? t("translating")
              : translation?.showing
                ? t("original")
                : t(target === "zh" ? "toChinese" : "toEnglish")}
          </Button>
          {translation?.text === undefined && <AiBadge feature="message_translate" />}
        </>
      )}
      {fellBack && (
        <span role="status" data-testid="voice-fell-back">
          {t("fellBack")}
        </span>
      )}
      {noChinese && (
        <span role="status" data-testid="no-chinese-voice">
          {t("noChineseVoice")}
        </span>
      )}
      {translation?.error && (
        <span role="alert" className="text-destructive">
          {translation.error}
        </span>
      )}
    </div>
  );
}
