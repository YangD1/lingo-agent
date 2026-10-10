"use client";

import { ArrowLeftIcon, EyeIcon, EyeOffIcon, Volume2Icon, VolumeXIcon } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import { AiBadge } from "@/components/ai-badge";
import { CatLoading, LingoCat } from "@/components/brand/lingo-cat";
import { SETTINGS_ERRORS } from "@/components/chat/attachment-tray";
import { MessageList } from "@/components/chat/message-list";
import { useChatSession } from "@/components/chat/use-chat-session";
import { useDescribeError } from "@/components/settings/use-describe-error";
import { Button, buttonVariants } from "@/components/ui/button";
import { ErrorText } from "@/components/ui/error-text";
import { Tag } from "@/components/ui/tag";
import { type ApiErrorLike, useErrorMessage } from "@/i18n/errors";
import { ApiError } from "@/lib/api";
import { useSpeakingAutoRead, useSpeakingHideText } from "@/lib/preferences";
import {
  endSession,
  fetchScenarios,
  fetchSession,
  type Scenario,
  scenarioGoal,
  scenarioTitle,
  type SpeakingSessionDetail,
} from "@/lib/speaking";
import { type SpeechStream, speakStream, stopSpeaking, useCanSpeak } from "@/lib/speech";

import { SpeakingInput } from "./speaking-input";
import { SpeakingSummaryView } from "./speaking-summary";

// Whose reading the replies are, for the stop button's state.
const READER = "speaking-reply";

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

  async function send(text: string, attachments?: Parameters<typeof session.send>[1]) {
    startReading();
    const sent = await session.send(text, attachments);
    endReading(sent);
    return sent;
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
        disabled={session.loading || ending}
        onSend={send}
        onStop={() => {
          session.stop();
          stopSpeaking();
        }}
      />
    </section>
  );
}
