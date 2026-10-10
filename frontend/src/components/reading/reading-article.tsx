"use client";

import { ArrowLeftIcon, ExternalLinkIcon, MessageCircleQuestionIcon } from "lucide-react";
import { useFormatter, useLocale, useTranslations } from "next-intl";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { AiBadge } from "@/components/ai-badge";
import { CatLoading } from "@/components/brand/lingo-cat";
import { WordPopup } from "@/components/chat/word-popup";
import { ReadingQuiz } from "@/components/reading/reading-quiz";
import { ShadowingBadge, ShadowingButton } from "@/components/speech/shadowing-button";
import { ShadowingPanel } from "@/components/speech/shadowing-panel";
import { useDescribeError } from "@/components/settings/use-describe-error";
import { Button, buttonVariants } from "@/components/ui/button";
import { Callout } from "@/components/ui/callout";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorText } from "@/components/ui/error-text";
import { Segmented } from "@/components/ui/segmented";
import { CefrTag, isCefrLevel, Tag } from "@/components/ui/tag";
import { api } from "@/lib/api";
import {
  fetchDueWords,
  fetchVersion,
  formOf,
  openReading,
  paragraphsOf,
  pieces,
  type ReadingSession,
  type Version,
} from "@/lib/reading";
import { shadowingSentences, useShadowingMode } from "@/lib/shadowing";
import type { Conversation } from "@/lib/types";
import { cn } from "@/lib/utils";

/** How often a version being written is checked. */
export const POLL_MS = 2000;

type View = "version" | "original";

/**
 * Reading one article (task 43.5): it opens at my level, rewritten if it can be (Q43g),
 * with the original a switch away. Words due for review today are highlighted, words past
 * my level underlined (Q43d), and any word opens the word popup. Questions are answered
 * once and graded on the server (Q43b); "Ask the tutor" opens reading_coach (Q43h).
 */
export function ReadingArticle({ id }: { id: number }) {
  const t = useTranslations("reading.article");
  const describe = useDescribeError();
  const [session, setSession] = useState<ReadingSession | null>(null);
  const [version, setVersion] = useState<Version | null>(null);
  const [view, setView] = useState<View>("version");
  const [error, setError] = useState<string | null>(null);
  const [retrying, setRetrying] = useState(false);

  const opened = useCallback((s: ReadingSession) => {
    setSession(s);
    setVersion(s.version);
    setError(null);
  }, []);

  useEffect(() => {
    let current = true;
    openReading(id).then(
      (s) => current && opened(s),
      (e: unknown) => current && setError(describe(e)),
    );
    return () => {
      current = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- describe is stable enough
  }, [id, opened]);

  // Poll a version being written until it is ready or failed.
  const generating = version?.status === "generating" ? version.id : null;
  useEffect(() => {
    if (!generating) return;
    const timer = setInterval(() => {
      fetchVersion(generating).then(setVersion, () => {});
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [generating]);

  async function retry() {
    setRetrying(true);
    try {
      opened(await openReading(id));
    } catch (e) {
      setError(describe(e));
    } finally {
      setRetrying(false);
    }
  }

  if (error && !session) {
    return (
      <Page>
        <BackLink />
        <EmptyState tone="error" title={error} />
      </Page>
    );
  }
  if (!session) {
    return (
      <Page>
        <CatLoading size={56} label={t("opening")} />
      </Page>
    );
  }

  const article = session.article;
  const ready = version?.status === "ready";
  const showing: View = ready && view === "version" ? "version" : "original";

  return (
    <Page>
      <BackLink />
      <Header session={session} version={ready ? version : null} showing={showing} />
      {ready && (
        <div className="flex flex-wrap items-center gap-2">
          <Segmented
            label={t("viewLabel")}
            value={view}
            onChange={setView}
            options={[
              { value: "version", label: t("viewVersion", { level: version.level }) },
              { value: "original", label: t("viewOriginal") },
            ]}
            data-testid="reading-view"
          />
          <AiBadge feature="reading_rewrite" />
        </div>
      )}
      {version?.status === "generating" && (
        <Callout tone="neutral" data-testid="reading-generating">
          <span className="flex items-center gap-3">
            <CatLoading size={40} label={t(`stage.${version.stage ?? "rewriting"}`)} />
          </span>
          <span className="mt-1 block text-xs text-muted-foreground">
            {t("generatingHint")} <AiBadge feature="reading_rewrite" />
          </span>
        </Callout>
      )}
      {version?.status === "failed" && (
        <Callout
          tone="warning"
          data-testid="reading-failed"
          action={
            <Button size="sm" variant="outline" disabled={retrying} onClick={() => void retry()}>
              {t("retry")}
            </Button>
          }
        >
          {t("failed", { code: version.error_code ?? "unknown" })}
        </Callout>
      )}
      {error && <ErrorText>{error}</ErrorText>}
      {session.original_reason && <Callout tone="neutral">{t(`reason.${session.original_reason}`)}</Callout>}

      {article.summary_only ? (
        <Summary session={session} />
      ) : (
        <Text session={session} version={showing === "version" ? version : null} />
      )}

      {ready && version.questions.length > 0 && (
        <ReadingQuiz
          sessionId={session.id}
          questions={version.questions}
          initial={session.results}
          onAnswered={(results) => setSession((s) => (s ? { ...s, results } : s))}
        />
      )}
      <AskTutor articleId={article.id} />
    </Page>
  );
}

function Page({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex-1 overflow-y-auto">
      <div className="mx-auto flex max-w-2xl flex-col gap-3.5 p-4 md:gap-4 md:px-10 md:py-8">{children}</div>
    </div>
  );
}

function BackLink() {
  const t = useTranslations("reading.article");
  return (
    <Link
      href="/reading"
      className="inline-flex items-center gap-1 self-start text-sm text-muted-foreground hover:text-foreground"
    >
      <ArrowLeftIcon aria-hidden className="size-4" />
      {t("back")}
    </Link>
  );
}

function Header({
  session,
  version,
  showing,
}: {
  session: ReadingSession;
  version: Version | null;
  showing: View;
}) {
  const t = useTranslations("reading.article");
  const format = useFormatter();
  const a = session.article;
  const title = showing === "version" && version?.title ? version.title : a.title;
  return (
    <header className="flex flex-col gap-1.5">
      <h1 lang="en" className="text-xl leading-snug font-semibold" data-testid="reading-title">
        {title}
      </h1>
      <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
        <span>{a.feed_title}</span>
        <span aria-hidden>·</span>
        <time dateTime={a.published_at}>{format.dateTime(new Date(a.published_at), { dateStyle: "medium" })}</time>
        {showing === "version" && version && (
          <>
            <span aria-hidden>·</span>
            <span className="tabular-nums">{t("words", { n: version.word_count })}</span>
            {isCefrLevel(version.level) ? <CefrTag level={version.level} /> : <Tag>{version.level}</Tag>}
          </>
        )}
        <a
          href={a.url}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-0.5 text-primary underline-offset-2 hover:underline"
        >
          {t("source")}
          <ExternalLinkIcon aria-hidden className="size-3" />
        </a>
      </p>
      <p className="text-xs text-muted-foreground" data-testid="reading-license">
        {showing === "version" ? t(`credit.${licenseKey(a.license)}`, { feed: a.feed_title }) : t("originalCredit", { feed: a.feed_title })}
        {a.author && ` · ${t("author", { author: a.author })}`}
      </p>
    </header>
  );
}

const licenseKey = (license: string) => (license === "cc_by" || license === "public_domain" ? license : "other");

function Summary({ session }: { session: ReadingSession }) {
  const t = useTranslations("reading.article");
  const container = useRef<HTMLDivElement>(null);
  return (
    <section className="flex flex-col gap-3">
      <div ref={container} lang="en" className="text-[15px] leading-relaxed">
        {paragraphsOf(session.article.body).map((p, i) => (
          <Paragraph key={i} text={p} due={new Set()} glossary={new Set()} />
        ))}
      </div>
      <WordPopup container={container} />
      <a
        href={session.article.url}
        target="_blank"
        rel="noopener noreferrer"
        className={cn(buttonVariants({ variant: "outline" }), "self-start")}
      >
        {t("readAtSource")}
        <ExternalLinkIcon aria-hidden />
      </a>
    </section>
  );
}

function Text({ session, version }: { session: ReadingSession; version: Version | null }) {
  const t = useTranslations("reading.article");
  const container = useRef<HTMLDivElement>(null);
  const original = version === null;
  const [due, setDue] = useState<{ key: string; forms: Set<string> } | null>(null);
  const key = `${session.id}:${original}`;

  useEffect(() => {
    let current = true;
    fetchDueWords(session.id, original).then(
      (marks) => current && setDue({ key, forms: new Set(marks.due.map((d) => d.form)) }),
      () => {},
    );
    return () => {
      current = false;
    };
  }, [session.id, original, key]);

  const paragraphs = useMemo(
    () => (version ? version.paragraphs : paragraphsOf(session.article.body)),
    [version, session.article.body],
  );
  const glossary = useMemo(() => new Set(version?.glossary.map((g) => g.form) ?? []), [version]);
  const dueForms = due?.key === key ? due.forms : new Set<string>();
  // The paragraph being shadowed, one at a time, in this version of the text (Q57b).
  const [shadowing, setShadowing] = useState<{ key: string; at: number } | null>(null);
  const shadowingAt = shadowing?.key === key ? shadowing.at : null;
  const shadowable = useShadowingMode() !== null;

  return (
    <section className="flex flex-col gap-2">
      {(dueForms.size > 0 || glossary.size > 0) && (
        <p className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground" data-testid="reading-legend">
          {dueForms.size > 0 && (
            <span>
              <mark className="rounded-sm bg-warning/25 px-1 text-foreground">{t("dueLegend")}</mark>{" "}
              {t("dueCount", { n: dueForms.size })}
            </span>
          )}
          {glossary.size > 0 && (
            <span>
              <span className="underline decoration-dotted underline-offset-4">{t("glossaryLegend")}</span>{" "}
              {t("glossaryCount", { n: glossary.size })}
            </span>
          )}
        </p>
      )}
      {shadowable && (
        <p className="flex items-center gap-1 text-xs text-muted-foreground" data-testid="reading-shadowing-hint">
          {t("shadowingHint")}
          <ShadowingBadge />
        </p>
      )}
      <div ref={container} lang="en" className="text-[15px] leading-relaxed" data-testid="reading-text">
        {paragraphs.map((p, i) => (
          <Paragraph
            key={i}
            text={p}
            due={dueForms}
            glossary={glossary}
            shadowing={
              shadowable
                ? {
                    open: shadowingAt === i,
                    toggle: () => setShadowing(shadowingAt === i ? null : { key, at: i }),
                    articleId: session.article.id,
                  }
                : undefined
            }
          />
        ))}
      </div>
      <WordPopup container={container} />
    </section>
  );
}

function Paragraph({
  text,
  due,
  glossary,
  shadowing,
}: {
  text: string;
  due: Set<string>;
  glossary: Set<string>;
  /** The microphone after the paragraph and the panel under it (Q57b): sentence by sentence. */
  shadowing?: { open: boolean; toggle: () => void; articleId: number };
}) {
  const t = useTranslations("speech.shadowing");
  const sentences = shadowing ? shadowingSentences(text) : [];
  const body = <ParagraphText text={text} due={due} glossary={glossary} />;
  if (!shadowing || sentences.length === 0) return body;
  return (
    <div className="my-3 first:mt-0 last:mb-0">
      <div className="flex items-start gap-1">
        <div className="min-w-0 flex-1 [&>p]:my-0">{body}</div>
        <ShadowingButton
          compact
          open={shadowing.open}
          onToggle={shadowing.toggle}
          label={t("openParagraph")}
          className="mt-0.5 shrink-0"
        />
      </div>
      {shadowing.open && (
        <ShadowingPanel
          sentences={sentences}
          source="reading"
          sourceId={String(shadowing.articleId)}
          onClose={shadowing.toggle}
          className="mt-2 font-sans"
        />
      )}
    </div>
  );
}

function ParagraphText({ text, due, glossary }: { text: string; due: Set<string>; glossary: Set<string> }) {
  return (
    <p className="my-3 first:mt-0 last:mb-0">
      {pieces(text).map((piece, i) => {
        if (!piece.word) return piece.text;
        const form = formOf(piece.text);
        return (
          <span
            key={i}
            data-word={piece.text}
            data-due={due.has(form) || undefined}
            data-glossary={glossary.has(form) || undefined}
            className={cn(
              "cursor-pointer rounded-sm transition-colors hover:bg-brand-soft hover:ring-2 hover:ring-brand-soft",
              due.has(form) && "bg-warning/25",
              glossary.has(form) && "underline decoration-dotted underline-offset-4",
            )}
          >
            {piece.text}
          </span>
        );
      })}
    </p>
  );
}

function AskTutor({ articleId }: { articleId: number }) {
  const t = useTranslations("reading.article");
  const describe = useDescribeError();
  const locale = useLocale();
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function ask() {
    setBusy(true);
    setError(null);
    try {
      const conversation = await api<Conversation>("/conversations", {
        method: "POST",
        json: { article_id: articleId, locale },
      });
      router.push(`/chat?c=${conversation.id}`);
    } catch (e) {
      setError(describe(e));
      setBusy(false);
    }
  }

  return (
    <section className="flex flex-col gap-2 border-t pt-4">
      <div className="flex flex-wrap items-center gap-2">
        <Button variant="outline" disabled={busy} onClick={() => void ask()} data-testid="reading-ask">
          <MessageCircleQuestionIcon aria-hidden />
          {t("ask")}
        </Button>
        <AiBadge feature="reading_coach" />
      </div>
      <p className="text-xs text-muted-foreground">{t("askHint")}</p>
      {error && <ErrorText>{error}</ErrorText>}
    </section>
  );
}
