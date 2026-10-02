"use client";

import { FileText, MessageCircle } from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { AiBadge } from "@/components/ai-badge";
import { CatLoading } from "@/components/brand/lingo-cat";
import { useDescribeError } from "@/components/settings/use-describe-error";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorText } from "@/components/ui/error-text";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { Tag } from "@/components/ui/tag";
import { Textarea } from "@/components/ui/textarea";
import { CEFR_LEVELS, type CefrLevel } from "@/lib/learner";
import { cn } from "@/lib/utils";
import {
  clearDraft,
  countWords,
  fetchSubmission,
  fetchSubmissions,
  fetchWritingPrompts,
  lengthProblem,
  loadDraft,
  MAX_WORDS,
  MIN_WORDS,
  saveDraft,
  type SubmissionBrief,
  submitWriting,
  type WritingPrompts,
} from "@/lib/writing";

/**
 * Writing (P2 plan §4.2, task 39): pick one of the fixed tasks for a level, write your
 * own task or none, write 20-800 words and submit; the review opens on its own page.
 * The text is kept as a draft in this browser until it is submitted (Q39d). `again`
 * (a failed or earlier submission) fills the form with that text to submit again (Q39e).
 */
export function WritingApp({ again }: { again: number | null }) {
  const t = useTranslations("writing");
  const describe = useDescribeError();
  const router = useRouter();
  const [text, setText] = useState("");
  const [prompt, setPrompt] = useState("");
  const [ownPrompt, setOwnPrompt] = useState(false);
  const [prompts, setPrompts] = useState<WritingPrompts | null>(null);
  const [history, setHistory] = useState<SubmissionBrief[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Drafts are saved only once the starting text is in, so it is never overwritten.
  const ready = useRef(false);

  useEffect(() => {
    const start = again
      ? fetchSubmission(again).then(
          (s) => ({ text: s.text, prompt: s.prompt }),
          () => loadDraft(),
        )
      : Promise.resolve(loadDraft());
    void start.then((draft) => {
      if (draft) {
        setText(draft.text);
        setPrompt(draft.prompt);
      }
      ready.current = true;
    });
    fetchWritingPrompts().then(setPrompts, (e: unknown) => setError(describe(e)));
    fetchSubmissions().then(setHistory, () => setHistory([]));
    // eslint-disable-next-line react-hooks/exhaustive-deps -- once
  }, []);

  useEffect(() => {
    if (ready.current) saveDraft({ text, prompt });
  }, [text, prompt]);

  function changeLevel(level: CefrLevel) {
    fetchWritingPrompts(level).then(setPrompts, (e: unknown) => setError(describe(e)));
  }

  async function submit() {
    if (lengthProblem(text) || busy) return;
    setBusy(true);
    setError(null);
    try {
      const submission = await submitWriting(text, prompt.trim());
      clearDraft();
      router.push(`/writing/${submission.id}`);
    } catch (e) {
      setError(describe(e));
      setBusy(false);
    }
  }

  const listed = prompts?.prompts.some((p) => p.en === prompt) ?? false;
  const showOwn = ownPrompt || (prompt !== "" && prompts !== null && !listed);
  const words = countWords(text);
  const problem = lengthProblem(text);

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="mx-auto flex max-w-2xl flex-col gap-3.5 p-4 md:gap-4 md:px-10 md:py-8">
        <Card data-testid="writing-form">
          <CardHeader>
            <CardTitle>
              <h1>{t("title")}</h1>
            </CardTitle>
            <CardDescription>{t("description")}</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-4 text-sm">
            <section className="flex flex-col gap-2" aria-labelledby="writing-task">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h2 id="writing-task" className="font-semibold">
                  {t("task.heading")}
                </h2>
                {prompts && (
                  <NativeSelect
                    aria-label={t("task.level")}
                    value={prompts.level}
                    onChange={(e) => changeLevel(e.target.value as CefrLevel)}
                    className="w-24"
                  >
                    {CEFR_LEVELS.map((level) => (
                      <option key={level} value={level}>
                        {level}
                      </option>
                    ))}
                  </NativeSelect>
                )}
              </div>
              {!prompts && !error && <CatLoading size={40} label={t("task.loading")} />}
              {prompts && (
                <ul className="flex flex-col gap-1.5" aria-label={t("task.heading")}>
                  {prompts.prompts.map((p) => (
                    <li key={p.id}>
                      <TaskButton
                        selected={!showOwn && prompt === p.en}
                        onClick={() => {
                          setOwnPrompt(false);
                          setPrompt(p.en);
                        }}
                      >
                        <span lang="en" className="block">
                          {p.en}
                        </span>
                        <span className="block text-xs text-muted-foreground">{p.zh}</span>
                      </TaskButton>
                    </li>
                  ))}
                  <li className="flex flex-wrap gap-1.5">
                    <TaskButton
                      compact
                      selected={showOwn}
                      onClick={() => {
                        setOwnPrompt(true);
                        if (listed) setPrompt("");
                      }}
                    >
                      {t("task.own")}
                    </TaskButton>
                    <TaskButton
                      compact
                      selected={!showOwn && prompt === ""}
                      onClick={() => {
                        setOwnPrompt(false);
                        setPrompt("");
                      }}
                    >
                      {t("task.none")}
                    </TaskButton>
                  </li>
                </ul>
              )}
              {showOwn && (
                <Input
                  aria-label={t("task.ownLabel")}
                  placeholder={t("task.ownPlaceholder")}
                  value={prompt}
                  maxLength={500}
                  onChange={(e) => setPrompt(e.target.value)}
                />
              )}
            </section>

            <section className="flex flex-col gap-2">
              <label htmlFor="writing-text" className="font-semibold">
                {t("text.label")}
              </label>
              <Textarea
                id="writing-text"
                lang="en"
                value={text}
                onChange={(e) => setText(e.target.value)}
                placeholder={t("text.placeholder")}
                aria-invalid={problem === "too_long" || undefined}
                aria-describedby="writing-count"
                className="min-h-56"
                data-testid="writing-text"
              />
              <p
                id="writing-count"
                className={cn(
                  "text-xs tabular-nums",
                  problem === "too_long" ? "text-destructive" : "text-muted-foreground",
                )}
                data-testid="writing-count"
              >
                {t("text.count", { n: words })}
                {" · "}
                {problem === "too_long"
                  ? t("text.tooLong", { max: MAX_WORDS })
                  : problem === "too_short"
                    ? t("text.tooShort", { min: MIN_WORDS })
                    : t("text.range", { min: MIN_WORDS, max: MAX_WORDS })}
              </p>
              <p className="text-xs text-muted-foreground">{t("text.draft")}</p>
            </section>

            {error && <ErrorText>{error}</ErrorText>}
            <div className="flex items-center gap-2">
              <Button
                disabled={busy || problem !== null}
                onClick={() => void submit()}
                data-testid="writing-submit"
              >
                {busy ? t("submitting") : t("submit")}
              </Button>
              <AiBadge feature="writing_submit" />
            </div>
          </CardContent>
        </Card>
        <History items={history} />
      </div>
    </div>
  );
}

function TaskButton({
  selected,
  compact = false,
  onClick,
  children,
}: {
  selected: boolean;
  compact?: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      aria-pressed={selected}
      onClick={onClick}
      className={cn(
        "rounded-lg border px-3 py-2 text-left transition-colors outline-none hover:bg-accent focus-visible:outline-2 focus-visible:outline-ring",
        compact ? "text-xs" : "w-full",
        selected && "border-primary bg-brand-soft text-brand-soft-foreground hover:bg-brand-soft",
      )}
    >
      {children}
    </button>
  );
}

function History({ items }: { items: SubmissionBrief[] | null }) {
  const t = useTranslations("writing.history");
  const format = useFormatter();
  return (
    <Card>
      <CardHeader>
        <CardTitle>
          <h2>{t("title")}</h2>
        </CardTitle>
      </CardHeader>
      <CardContent>
        {items === null ? (
          <CatLoading size={40} label={t("loading")} />
        ) : items.length === 0 ? (
          <EmptyState title={t("none")} />
        ) : (
          <ul className="flex flex-col divide-y text-sm" aria-label={t("title")}>
            {items.map((s) => (
              <li key={s.id} data-testid="writing-history">
                <Link
                  href={`/writing/${s.id}`}
                  className="flex items-center gap-3 rounded-md py-2.5 outline-none hover:bg-accent/50 focus-visible:outline-2 focus-visible:outline-ring"
                >
                  {s.from_conversation ? (
                    <MessageCircle aria-hidden className="size-4 shrink-0 text-muted-foreground" />
                  ) : (
                    <FileText aria-hidden className="size-4 shrink-0 text-muted-foreground" />
                  )}
                  <span className="flex min-w-0 flex-1 flex-col">
                    <span className="truncate font-[550]" lang="en">
                      {s.prompt || s.excerpt}
                    </span>
                    <span className="text-xs text-muted-foreground">
                      {format.dateTime(new Date(s.created_at), {
                        dateStyle: "medium",
                        timeStyle: "short",
                      })}
                      {" · "}
                      {t("words", { n: s.word_count })}
                      {s.from_conversation && ` · ${t("fromChat")}`}
                    </span>
                  </span>
                  <Status brief={s} />
                </Link>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

function Status({ brief }: { brief: SubmissionBrief }) {
  const t = useTranslations("writing.history");
  if (brief.status === "pending") return <Tag>{t("pending")}</Tag>;
  if (brief.status === "failed") return <Tag variant="warning">{t("failed")}</Tag>;
  return (
    <span className="text-xs text-muted-foreground tabular-nums">
      {brief.mistakes === 0 ? t("noMistakes") : t("mistakes", { n: brief.mistakes })}
    </span>
  );
}
