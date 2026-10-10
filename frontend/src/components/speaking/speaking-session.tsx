"use client";

import { ArrowLeftIcon, EyeIcon, EyeOffIcon, PencilIcon, Volume2Icon, VolumeXIcon } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import { AiBadge } from "@/components/ai-badge";
import { CatLoading, LingoCat } from "@/components/brand/lingo-cat";
import { SETTINGS_ERRORS } from "@/components/chat/attachment-tray";
import { MessageList } from "@/components/chat/message-list";
import { type ChatMessage, useChatSession } from "@/components/chat/use-chat-session";
import { useDescribeError } from "@/components/settings/use-describe-error";
import { Button, buttonVariants } from "@/components/ui/button";
import { ErrorText } from "@/components/ui/error-text";
import { Tag } from "@/components/ui/tag";
import { Textarea } from "@/components/ui/textarea";
import { type ApiErrorLike, useErrorMessage } from "@/i18n/errors";
import { ApiError } from "@/lib/api";
import { deleteAttachment, getAttachment, retryAttachment, uploadAttachment } from "@/lib/attachments";
import { useSpeakingAutoRead, useSpeakingHideText } from "@/lib/preferences";
import {
  correctTranscript,
  endSession,
  fetchScenarios,
  fetchSession,
  type Scenario,
  scenarioGoal,
  scenarioTitle,
  type SpeakingSessionDetail,
} from "@/lib/speaking";
import { type SpeechStream, speakStream, stopSpeaking, useCanSpeak, useServerSpeech } from "@/lib/speech";
import type { Attachment } from "@/lib/types";

import { SpeakingInput } from "./speaking-input";
import { SpeakingSummaryView } from "./speaking-summary";

// Whose reading the replies are, for the stop button's state.
const READER = "speaking-reply";
// How often a voice message being transcribed is asked about.
export const POLL_MS = 1000;

/** A voice message on its way: being transcribed, or what went wrong (Q59b). */
type Pending =
  | { state: "transcribing" }
  | { state: "empty" }
  | { state: "failed"; attachment: Attachment | null; error: ApiErrorLike | null; file: File };

const asError = (e: unknown): ApiErrorLike =>
  e instanceof ApiError ? e : { code: "network_error", message: String(e) };

/**
 * One speaking practice (task 59.3, ADR 0029 §3): the conversation while it is open, its
 * summary once it has ended.
 */
export function SpeakingSessionPage({ id }: { id: string }) {
  const t = useTranslations("speaking.session");
  const describe = useDescribeError();
  const [detail, setDetail] = useState<SpeakingSessionDetail | null>(null);
  const [scenario, setScenario] = useState<Scenario | null>(null);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(
    () => fetchSession(id).then(setDetail, (e: unknown) => setError(describe(e))),
    // eslint-disable-next-line react-hooks/exhaustive-deps -- describe is stable enough
    [id],
  );

  useEffect(() => {
    void reload();
  }, [reload]);

  const scenarioId = detail?.scenario_id;
  useEffect(() => {
    if (!scenarioId) return;
    fetchScenarios().then(
      (all) => setScenario(all.scenarios.find((s) => s.id === scenarioId) ?? null),
      () => {}, // only the header's title and goal: free talk's are shown instead
    );
  }, [scenarioId]);

  if (error) {
    return (
      <div className="mx-auto w-full max-w-2xl p-4 md:px-10 md:py-8">
        <ErrorText>{error}</ErrorText>
      </div>
    );
  }
  if (!detail) return <CatLoading size={48} className="m-auto" label={t("loading")} />;
  if (detail.status === "active") {
    return <SpeakingTalk detail={detail} scenario={scenario} onEnded={setDetail} onStale={reload} />;
  }
  return <SpeakingSummaryView detail={detail} scenario={scenario} onChange={setDetail} />;
}

function SpeakingTalk({
  detail,
  scenario,
  onEnded,
  onStale,
}: {
  detail: SpeakingSessionDetail;
  scenario: Scenario | null;
  /** The practice ended here: its summary, or a failed one to retry. */
  onEnded: (detail: SpeakingSessionDetail) => void;
  /** It ended elsewhere (another tab, or summed up after idling): load it again. */
  onStale: () => void;
}) {
  const t = useTranslations("speaking.session");
  const locale = useLocale();
  const errorMessage = useErrorMessage();
  const canSpeak = useCanSpeak();
  const [autoRead, setAutoRead] = useSpeakingAutoRead();
  const [hideText, setHideText] = useSpeakingHideText();
  const [ending, setEnding] = useState(false);
  const [endError, setEndError] = useState<ApiErrorLike | null>(null);
  const { asr } = useServerSpeech();
  const [typing, setTyping] = useState(false);
  const [pending, setPending] = useState<Pending | null>(null);
  // Learner turns whose transcript was fixed and sent again (Q58b, Q59c).
  const [corrected, setCorrected] = useState(() => new Set(detail.corrected_message_ids));
  const alive = useRef(true);
  useEffect(
    () => () => {
      alive.current = false;
    },
    [],
  );

  // The reply being read aloud as it streams; started inside the click that sent the
  // message, so Safari lets it play (task 59.1).
  const reader = useRef<SpeechStream | null>(null);
  const session = useChatSession(detail.conversation_id, {
    onConversationCreated: () => {},
    onTurnFinished: () => {},
    onToken: (text) => reader.current?.push(text),
  });

  const startReading = () => {
    reader.current = autoRead && canSpeak ? speakStream(READER) : null;
  };
  const endReading = (spoken: boolean) => {
    if (spoken) reader.current?.end();
    else if (reader.current) stopSpeaking();
    reader.current = null;
  };

  async function send(text: string, attachments?: Attachment[]) {
    startReading();
    const sent = await session.send(text, attachments);
    endReading(sent);
    return sent;
  }

  /**
   * Transcribes a recording and sends the transcript straight away (Q59b): nothing is
   * sent when nothing was heard; a failure can be retried, or the turn typed instead.
   */
  async function sendVoice(file: File, retry?: Attachment) {
    setPending({ state: "transcribing" });
    let attachment = retry ?? null;
    try {
      attachment = retry ? await retryAttachment(retry.id) : await uploadAttachment(detail.conversation_id, file);
      while (attachment.status === "processing") {
        await new Promise((resolve) => setTimeout(resolve, POLL_MS));
        if (!alive.current) return;
        attachment = await getAttachment(attachment.id);
      }
    } catch (e) {
      if (alive.current) setPending({ state: "failed", attachment, error: asError(e), file });
      return;
    }
    if (!alive.current) return;
    if (attachment.status === "failed") {
      return setPending({ state: "failed", attachment, error: null, file });
    }
    if (!attachment.text?.trim()) {
      void deleteAttachment(attachment.id).catch(() => {});
      return setPending({ state: "empty" });
    }
    setPending(null);
    await send("", [attachment]);
  }

  function dropPending() {
    if (pending?.state === "failed" && pending.attachment) {
      void deleteAttachment(pending.attachment.id).catch(() => {});
    }
    setPending(null);
  }

  /** The fixed transcript goes as a new message; the old one counts as nothing (Q58b). */
  async function resend(message: ChatMessage, text: string) {
    if (!message.id) return false;
    try {
      await correctTranscript(detail.id, message.id);
    } catch (e) {
      setEndError(asError(e));
      return false;
    }
    setCorrected((all) => new Set(all).add(message.id!));
    return send(text);
  }

  // The tutor speaks first (Q58e): once per page load, so a refusal doesn't loop.
  const opened = useRef(false);
  const { readyFor, messages, streaming, open } = session;
  useEffect(() => {
    if (opened.current || readyFor !== detail.conversation_id) return;
    if (messages.length > 0 || streaming) return;
    opened.current = true;
    startReading();
    void open().then(() => endReading(true));
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reading is set up per call
  }, [readyFor, detail.conversation_id, messages.length, streaming, open]);

  // Ended in another tab, or summed up after it idled: show the summary instead.
  const error = session.error ?? endError;
  useEffect(() => {
    if (error?.code === "speaking_ended") onStale();
  }, [error, onStale]);

  async function end() {
    setEnding(true);
    setEndError(null);
    stopSpeaking();
    try {
      onEnded(await endSession(detail.id));
    } catch (e) {
      setEndError(e instanceof ApiError ? e : { code: "network_error", message: String(e) });
      setEnding(false);
    }
  }

  const title = scenario ? scenarioTitle(scenario, locale) : t("freeTalk");
  const goal = scenario ? scenarioGoal(scenario, locale) : t("freeTalkGoal");
  const said = messages.some((m) => m.role === "user");

  return (
    <section className="flex min-h-0 min-w-0 flex-1 flex-col">
      <header className="mx-auto flex w-full max-w-3xl flex-col gap-2 border-b px-3 py-3 md:px-8">
        <div className="flex items-center gap-2">
          <Link
            href="/speaking"
            aria-label={t("back")}
            className={buttonVariants({ size: "icon-sm", variant: "ghost" })}
          >
            <ArrowLeftIcon />
          </Link>
          <h1 className="min-w-0 flex-1 truncate text-base font-semibold">{title}</h1>
          <Button
            size="icon-sm"
            variant="ghost"
            aria-pressed={autoRead}
            aria-label={t("autoRead")}
            title={t("autoRead")}
            onClick={() => {
              if (autoRead) stopSpeaking();
              setAutoRead(!autoRead);
            }}
          >
            {autoRead ? <Volume2Icon /> : <VolumeXIcon />}
          </Button>
          <Button
            size="icon-sm"
            variant="ghost"
            aria-pressed={hideText}
            aria-label={t("hideText")}
            title={t("hideText")}
            onClick={() => setHideText(!hideText)}
          >
            {hideText ? <EyeOffIcon /> : <EyeIcon />}
          </Button>
          <Button
            size="sm"
            variant="outline"
            disabled={ending || streaming}
            onClick={() => void end()}
            data-testid="speaking-end"
          >
            {ending ? t("ending") : said ? t("end") : t("leave")}
            {said && <AiBadge feature="speaking_summary" />}
          </Button>
        </div>
        <p className="text-sm text-muted-foreground">{goal}</p>
        {scenario && scenario.target_expressions.length > 0 && (
          <p className="flex flex-wrap items-center gap-1 text-xs text-muted-foreground">
            {t("tryUsing")}
            <span lang="en" className="flex flex-wrap gap-1">
              {scenario.target_expressions.map((e) => (
                <Tag key={e}>{e}</Tag>
              ))}
            </span>
          </p>
        )}
      </header>
      <MessageList
        conversationId={detail.conversation_id}
        messages={messages}
        hideReplyText={hideText}
        empty={<CatLoading size={48} className="m-auto" label={t("opening")} />}
        struck={(m) => m.id !== undefined && corrected.has(m.id)}
        userFooter={(m, last) =>
          last &&
          !streaming &&
          m.id &&
          !corrected.has(m.id) &&
          m.attachments?.some((a) => a.kind === "audio") ? (
            <FixTranscript message={m} onResend={(text) => resend(m, text)} />
          ) : m.id && corrected.has(m.id) ? (
            <Tag variant="outline">{t("fixed")}</Tag>
          ) : null
        }
        tail={
          pending && (
            <PendingVoice
              pending={pending}
              onRetry={() =>
                pending.state === "failed" && void sendVoice(pending.file, pending.attachment ?? undefined)
              }
              onType={() => {
                dropPending();
                setTyping(true);
              }}
              onDismiss={dropPending}
            />
          )
        }
      />
      {error && error.code !== "speaking_ended" && (
        <div
          role="alert"
          className="mx-auto flex w-full max-w-3xl items-center gap-3 px-3 text-sm text-destructive md:px-8"
        >
          <LingoCat mood="oops" size={20} label="" />
          <span className="flex-1">{errorMessage(error)}</span>
          {SETTINGS_ERRORS.has(error.code) && (
            <Link href="/settings" className={buttonVariants({ size: "sm", variant: "outline" })}>
              {t("goToSettings")}
            </Link>
          )}
        </div>
      )}
      <SpeakingInput
        streaming={streaming}
        disabled={session.loading || ending || pending?.state === "transcribing"}
        voice={asr === true}
        typing={typing}
        onTypingChange={setTyping}
        onSend={send}
        onVoice={(file) => void sendVoice(file)}
        onStop={() => {
          session.stop();
          stopSpeaking();
        }}
      />
    </section>
  );
}

/** "Fix it" under the learner's last voice message: edit the transcript in place (Q59c). */
function FixTranscript({
  message,
  onResend,
}: {
  message: ChatMessage;
  onResend: (text: string) => Promise<boolean>;
}) {
  const t = useTranslations("speaking.session");
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(message.content);
  const [busy, setBusy] = useState(false);
  if (!editing) {
    return (
      <Button size="xs" variant="ghost" onClick={() => setEditing(true)} data-testid="speaking-fix">
        <PencilIcon />
        {t("fix")}
      </Button>
    );
  }
  const unchanged = text.trim() === message.content.trim() || !text.trim();
  return (
    <div className="flex w-full min-w-64 flex-col gap-1.5">
      <Textarea
        lang="en"
        value={text}
        onChange={(e) => setText(e.target.value)}
        aria-label={t("fixLabel")}
        rows={2}
        autoFocus
      />
      <p className="text-xs text-muted-foreground">{t("fixHint")}</p>
      <div className="flex justify-end gap-1.5">
        <Button size="sm" variant="ghost" onClick={() => setEditing(false)} disabled={busy}>
          {t("cancel")}
        </Button>
        <Button
          size="sm"
          disabled={unchanged || busy}
          onClick={async () => {
            setBusy(true);
            if (!(await onResend(text.trim()))) setBusy(false);
          }}
        >
          {t("fixSend")}
        </Button>
      </div>
    </div>
  );
}

/** A voice message being transcribed, or why it wasn't sent (Q59b). */
function PendingVoice({
  pending,
  onRetry,
  onType,
  onDismiss,
}: {
  pending: Pending;
  onRetry: () => void;
  onType: () => void;
  onDismiss: () => void;
}) {
  const t = useTranslations("speaking.session");
  const errorMessage = useErrorMessage();
  return (
    <li data-role="user" data-testid="speaking-pending" data-state={pending.state} className="flex flex-col items-end gap-1 self-end">
      <div className="rounded-[18px_18px_6px_18px] border border-dashed border-primary/50 bg-brand-soft px-[15px] py-2.5 text-sm text-brand-soft-foreground">
        {pending.state === "transcribing" && <span role="status">{t("transcribing")}</span>}
        {pending.state === "empty" && t("notHeard")}
        {pending.state === "failed" && (pending.error ? errorMessage(pending.error) : t("transcribeFailed"))}
      </div>
      {pending.state === "failed" && (
        <div className="flex gap-1.5">
          <Button size="xs" variant="ghost" onClick={onType}>
            {t("typeInstead")}
          </Button>
          <Button size="xs" variant="outline" onClick={onRetry}>
            {t("retry")}
          </Button>
        </div>
      )}
      {pending.state === "empty" && (
        <Button size="xs" variant="ghost" onClick={onDismiss}>
          {t("ok")}
        </Button>
      )}
    </li>
  );
}
