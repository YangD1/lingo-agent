"use client";

import { ArrowUp, KeyboardIcon, MicIcon, Square } from "lucide-react";
import { useTranslations } from "next-intl";
import {
  type FormEvent,
  type KeyboardEvent,
  type PointerEvent,
  useEffect,
  useRef,
  useState,
} from "react";

import { AiBadge } from "@/components/ai-badge";
import { LevelMeter } from "@/components/chat/composer";
import { useRecorder } from "@/components/chat/use-recorder";
import { Button } from "@/components/ui/button";
import { ErrorText } from "@/components/ui/error-text";
import { Textarea } from "@/components/ui/textarea";
import { stopSpeaking, unlockSpeech } from "@/lib/speech";
import { cn } from "@/lib/utils";

// The backend's limit on a message.
const MAX_LENGTH = 4000;
// A spoken turn is short; one this long stops on its own (Q59a).
export const MAX_TURN_SECONDS = 60;
// Released sooner than this after pressing: a tap, and the next tap sends (Q59a).
export const TAP_MS = 300;

/**
 * What the learner says in a speaking practice (tasks 59.3–59.4): by voice when speech-
 * to-text is set up, else typed; the keyboard button switches. One microphone button:
 * hold to talk and release to send, or tap to start and tap again to send; released
 * outside the button, the recording is dropped. Space does the same on a desktop.
 * `onSend` resolves false when nothing was sent, and the text stays.
 */
export function SpeakingInput({
  streaming,
  disabled,
  voice: canVoice,
  onSend,
  onVoice,
  onStop,
  typing,
  onTypingChange,
}: {
  streaming: boolean;
  disabled: boolean;
  /** Speech-to-text is set up: voice turns can be taken. */
  voice: boolean;
  onSend: (text: string) => Promise<boolean>;
  /** A finished recording, to transcribe and send (Q59b). */
  onVoice: (file: File) => void;
  onStop: () => void;
  /** Typing instead of talking. */
  typing: boolean;
  onTypingChange: (typing: boolean) => void;
}) {
  const t = useTranslations("speaking.session");
  const tChat = useTranslations("chat");
  const [text, setText] = useState("");
  const recorder = useRecorder(onVoice, { maxSeconds: MAX_TURN_SECONDS });
  // How the recording now going was started: held down, or tapped (and sent by a tap).
  const press = useRef<{ at: number; tapped: boolean } | null>(null);
  const [outside, setOutside] = useState(false);
  // `press.current.tapped`, for what the hint says.
  const [tapped, setTapped] = useState(false);
  const empty = !text.trim();
  const talking = canVoice && !typing;
  const busy = streaming || disabled;

  async function submit(event?: FormEvent) {
    event?.preventDefault();
    if (empty || busy) return;
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

  function begin(tapped = false) {
    stopSpeaking(); // the tutor stops when the learner starts talking
    press.current = { at: Date.now(), tapped };
    setTapped(tapped);
    setOutside(false);
    void recorder.start();
  }

  function finish(keep: boolean) {
    press.current = null;
    setTapped(false);
    setOutside(false);
    if (!keep) return recorder.cancel();
    unlockSpeech(); // inside the release: the reply is read once it comes
    recorder.stop();
  }

  function onPointerDown(event: PointerEvent<HTMLButtonElement>) {
    if (event.button !== 0 || busy) return;
    event.currentTarget.setPointerCapture?.(event.pointerId);
    if (press.current?.tapped) return; // the tap that sends: handled on release
    begin();
  }

  function inside(event: PointerEvent<HTMLButtonElement>) {
    const box = event.currentTarget.getBoundingClientRect();
    return (
      event.clientX >= box.left &&
      event.clientX <= box.right &&
      event.clientY >= box.top &&
      event.clientY <= box.bottom
    );
  }

  function onPointerUp(event: PointerEvent<HTMLButtonElement>) {
    const current = press.current;
    if (!current) return;
    if (current.tapped) return finish(true);
    if (Date.now() - current.at < TAP_MS) {
      press.current = { ...current, tapped: true }; // recording on until the next tap
      setTapped(true);
      return;
    }
    finish(inside(event));
  }

  function onPointerMove(event: PointerEvent<HTMLButtonElement>) {
    if (press.current && !press.current.tapped) setOutside(!inside(event));
  }

  // Space held down on a desktop talks, unless typing somewhere.
  const spaceRef = useRef({ begin, finish, talking, busy });
  useEffect(() => {
    spaceRef.current = { begin, finish, talking, busy };
  });
  useEffect(() => {
    const typingIn = (target: EventTarget | null) =>
      target instanceof HTMLElement &&
      (target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName));
    const down = (event: globalThis.KeyboardEvent) => {
      const s = spaceRef.current;
      if (event.code !== "Space" || event.repeat || !s.talking || s.busy || typingIn(event.target)) return;
      event.preventDefault();
      if (!press.current) s.begin(true);
    };
    const up = (event: globalThis.KeyboardEvent) => {
      if (event.code !== "Space" || !press.current?.tapped || typingIn(event.target)) return;
      event.preventDefault();
      spaceRef.current.finish(true);
    };
    window.addEventListener("keydown", down);
    window.addEventListener("keyup", up);
    return () => {
      window.removeEventListener("keydown", down);
      window.removeEventListener("keyup", up);
    };
  }, []);

  // The recording stopped on its own (too long): the press is over.
  useEffect(() => {
    if (!recorder.recording) press.current = null; // `tapped` is reset on the next press
  }, [recorder.recording]);

  const hint = !recorder.recording
    ? t("holdToTalk")
    : outside
      ? t("releaseToCancel")
      : tapped
        ? t("tapToSend")
        : t("releaseToSend");

  return (
    <form onSubmit={submit} className="w-full px-2.5 pt-1.5 pb-3 md:px-8 md:pt-2 md:pb-5">
      <div className="mx-auto flex max-w-3xl flex-col gap-1.5">
        {talking ? (
          <div className="flex items-center justify-center gap-3">
            <Button
              type="button"
              size="icon"
              variant="ghost"
              aria-label={t("typeInstead")}
              title={t("typeInstead")}
              disabled={recorder.recording}
              onClick={() => onTypingChange(true)}
            >
              <KeyboardIcon />
            </Button>
            <div className="relative flex flex-col items-center gap-1.5">
              <button
                type="button"
                data-testid="speaking-mic"
                data-recording={recorder.recording || undefined}
                aria-label={hint}
                aria-pressed={recorder.recording}
                disabled={busy && !recorder.recording}
                onPointerDown={onPointerDown}
                onPointerUp={onPointerUp}
                onPointerMove={onPointerMove}
                onPointerCancel={() => press.current && finish(false)}
                onContextMenu={(e) => e.preventDefault()}
                className={cn(
                  "flex size-16 touch-none items-center justify-center rounded-full bg-primary text-primary-foreground shadow-(--shadow-lift) transition-[transform,background-color] outline-none select-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring disabled:opacity-45",
                  recorder.recording && "scale-110 bg-destructive",
                  outside && "bg-muted text-muted-foreground",
                )}
              >
                <MicIcon className="size-7" aria-hidden />
              </button>
              <AiBadge feature="speaking_turn" corner />
            </div>
            {streaming ? (
              <Button type="button" variant="outline" onClick={onStop}>
                <Square className="size-3 fill-current" />
                {t("stop")}
              </Button>
            ) : (
              <span className="size-10 md:size-9" aria-hidden />
            )}
          </div>
        ) : (
          <div className="flex items-end gap-2 rounded-[18px] border border-input bg-card p-2 shadow-(--shadow-lift) focus-within:border-ring focus-within:ring-3 focus-within:ring-ring/20">
            {canVoice && (
              <Button
                type="button"
                size="icon"
                variant="ghost"
                aria-label={t("talkInstead")}
                title={t("talkInstead")}
                onClick={() => onTypingChange(false)}
              >
                <MicIcon />
              </Button>
            )}
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
                <Button type="submit" disabled={empty || busy}>
                  <ArrowUp />
                  {t("send")}
                </Button>
                <AiBadge feature="speaking_turn" corner />
              </div>
            )}
          </div>
        )}
        {talking && (
          <p className="flex items-center justify-center gap-2 text-xs text-muted-foreground" aria-live="polite">
            {recorder.recording && <LevelMeter level={recorder.level} />}
            {recorder.recording && (
              <span className="tabular-nums">
                {recorder.seconds}s / {MAX_TURN_SECONDS}s
              </span>
            )}
            <span>{hint}</span>
          </p>
        )}
        {recorder.error && (
          <ErrorText size="xs" className="justify-center">
            {tChat(`attachments.${recorder.error}`)}
          </ErrorText>
        )}
      </div>
    </form>
  );
}
