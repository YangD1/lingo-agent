"use client";

import { ScanText, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { Fragment, type ReactNode, useCallback, useEffect, useRef, useState } from "react";

import { AiBadge } from "@/components/ai-badge";
import { WordPopup } from "@/components/chat/word-popup";
import { useDescribeError } from "@/components/settings/use-describe-error";
import { ShadowingButton } from "@/components/speech/shadowing-button";
import { ShadowingPanel } from "@/components/speech/shadowing-panel";
import { Button } from "@/components/ui/button";
import { Segmented } from "@/components/ui/segmented";
import { pieces } from "@/lib/reading";
import { shadowingSentences, useShadowingMode } from "@/lib/shadowing";
import { cn } from "@/lib/utils";
import {
  type ReadingDisplay,
  type SentenceAnalysis,
  type WorkspaceDocDetail,
  analyzeSentence,
  nextToTranslate,
  sentencesOf,
  translateParagraphs,
} from "@/lib/workspace";

type Translated = { text: string } | { error: string };

/** One version's translations: a new version starts over (the text changed). */
type Translations = { key: string; found: Map<number, Translated> };

type Analysis = { status: "loading" } | { status: "ok"; data: SentenceAnalysis } | { status: "error"; error: string };

/** Open analyses by "paragraph:sentence", several at once (Q83h). */
type Analyses = { key: string; open: Map<string, Analysis> };

/**
 * A reading document (ADR 0043 §4): the original, side by side with its translation or the
 * translation alone, translated paragraph by paragraph as they scroll into view. Words open
 * the word popup; in "analyse" mode a sentence opens its structure under it instead.
 */
export function ReadingView({ doc }: { doc: WorkspaceDocDetail }) {
  const t = useTranslations("chat.workspace.reading");
  const describe = useDescribeError();
  const paragraphs = doc.content.paragraphs ?? [];
  const key = `${doc.id}:${doc.version}`;
  const container = useRef<HTMLDivElement>(null);

  const [display, setDisplay] = useState<ReadingDisplay>("original");
  const [analysing, setAnalysing] = useState(false);
  const [shadowing, setShadowing] = useState<{ key: string; at: number } | null>(null);
  const shadowingAt = shadowing?.key === key ? shadowing.at : null;
  const shadowable = useShadowingMode() !== null;

  // Translations, kept per version and requested one batch at a time.
  const [translations, setTranslations] = useState<Translations>({ key, found: new Map() });
  const found = translations.key === key ? translations.found : null;
  const visible = useRef(new Set<number>());
  const pending = useRef(new Set<number>());
  const busy = useRef(false);
  const current = useRef(key);

  const pump = useCallback(() => {
    if (busy.current) return;
    const done = new Set(translations.key === key ? translations.found.keys() : []);
    const batch = nextToTranslate(visible.current, done, pending.current);
    if (batch.length === 0) return;
    busy.current = true;
    batch.forEach((i) => pending.current.add(i));
    const settle = (add: (map: Map<number, Translated>) => void) => {
      // A newer version came in meanwhile: its paragraphs are other ones.
      if (current.current !== key) return;
      batch.forEach((i) => pending.current.delete(i));
      busy.current = false;
      // The new state pumps the next batch (the effect below).
      setTranslations((prev) => {
        const map = new Map(prev.key === key ? prev.found : []);
        add(map);
        return { key, found: map };
      });
    };
    translateParagraphs(doc.id, batch).then(
      (result) =>
        settle((map) => {
          if (result.version !== doc.version) return;
          result.translations.forEach((p) => map.set(p.index, { text: p.text }));
        }),
      (e: unknown) => {
        const error = describe(e);
        settle((map) => batch.forEach((i) => map.set(i, { error })));
      },
    );
  }, [doc.id, doc.version, key, translations, describe]);

  // After each answer the next batch goes out; the observer below calls the latest pump.
  const latestPump = useRef(pump);
  useEffect(() => {
    latestPump.current = pump;
    if (display !== "original") pump();
  }, [display, pump]);

  // A new version: nothing in view is known to be translated, nothing is on the way.
  useEffect(() => {
    current.current = key;
    pending.current = new Set();
    busy.current = false;
  }, [key]);

  useEffect(() => {
    const box = container.current;
    if (display === "original" || !box || typeof IntersectionObserver === "undefined") return;
    const seen = visible.current;
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          const i = Number((entry.target as HTMLElement).dataset.paragraph);
          if (entry.isIntersecting) seen.add(i);
          else seen.delete(i);
        }
        latestPump.current();
      },
      // A little ahead of the reader, so the next paragraph is ready when it arrives.
      { rootMargin: "300px 0px" },
    );
    box.querySelectorAll("[data-paragraph]").forEach((el) => observer.observe(el));
    return () => {
      observer.disconnect();
      seen.clear();
    };
  }, [display, key]);

  const retry = (i: number) =>
    setTranslations((prev) => {
      const map = new Map(prev.found);
      map.delete(i);
      return { key: prev.key, found: map };
    });

  // Sentence analyses, per version too.
  const [analyses, setAnalyses] = useState<Analyses>({ key, open: new Map() });
  const open = analyses.key === key ? analyses.open : new Map<string, Analysis>();
  const setAnalysis = (id: string, analysis: Analysis | null) =>
    setAnalyses((prev) => {
      const map = new Map(prev.key === key ? prev.open : []);
      if (analysis) map.set(id, analysis);
      else map.delete(id);
      return { key, open: map };
    });

  const loadSentence = (paragraph: number, sentence: number, text: string) => {
    const id = `${paragraph}:${sentence}`;
    setAnalysis(id, { status: "loading" });
    analyzeSentence(doc.id, paragraph, text.trim()).then(
      (data) => setAnalysis(id, { status: "ok", data }),
      (e: unknown) => setAnalysis(id, { status: "error", error: describe(e) }),
    );
  };
  const toggleSentence = (paragraph: number, sentence: number, text: string) =>
    open.has(`${paragraph}:${sentence}`)
      ? setAnalysis(`${paragraph}:${sentence}`, null)
      : loadSentence(paragraph, sentence, text);

  const shadowingSource = doc.source === "article" ? (doc.source_ref ?? undefined) : undefined;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2" data-testid="reading-toolbar">
        <Segmented
          label={t("display")}
          size="sm"
          value={display}
          onChange={setDisplay}
          options={[
            { value: "original", label: t("original") },
            { value: "both", label: t("both") },
            { value: "translation", label: t("translation") },
          ]}
        />
        <AiBadge feature="workspace_translate" />
        <span className="flex-1" />
        <Button
          size="sm"
          variant={analysing ? "secondary" : "ghost"}
          aria-pressed={analysing}
          onClick={() => setAnalysing((on) => !on)}
          data-testid="reading-analyse"
        >
          <ScanText />
          {t("analyse")}
        </Button>
        <AiBadge feature="workspace_analyze" />
      </div>
      {analysing && (
        <p className="-mt-2 text-xs text-muted-foreground" role="status">
          {t("analyseHint")}
        </p>
      )}
      <div ref={container} className="@container flex flex-col gap-4 text-[15px] leading-7" data-testid="workspace-text">
        {paragraphs.map((text, i) => {
          const translated = found?.get(i);
          const original = (
            <div lang="en" className="min-w-0">
              <OriginalParagraph
                text={text}
                analysing={analysing}
                open={(s) => open.get(`${i}:${s}`)}
                onSentence={(s, sentence) => toggleSentence(i, s, sentence)}
                onRetry={(s, sentence) => loadSentence(i, s, sentence)}
                shadowing={
                  shadowable
                    ? {
                        open: shadowingAt === i,
                        toggle: () => setShadowing(shadowingAt === i ? null : { key, at: i }),
                      }
                    : undefined
                }
              />
              {shadowingAt === i && (
                <ShadowingPanel
                  sentences={shadowingSentences(text)}
                  source="reading"
                  sourceId={shadowingSource}
                  onClose={() => setShadowing(null)}
                  className="mt-2"
                />
              )}
            </div>
          );
          const translation = (
            <TranslatedParagraph translated={translated} onRetry={() => retry(i)} />
          );
          return (
            <div
              key={`${key}:${i}`}
              data-paragraph={i}
              className={cn(display === "both" && "grid gap-x-6 gap-y-1 @2xl:grid-cols-2")}
            >
              {display !== "translation" && original}
              {display !== "original" && translation}
            </div>
          );
        })}
      </div>
      {/* Words open their popup unless a sentence tap is meant (analyse mode). */}
      <WordPopup container={container} />
    </div>
  );
}

function TranslatedParagraph({ translated, onRetry }: { translated?: Translated; onRetry: () => void }) {
  const t = useTranslations("chat.workspace.reading");
  if (!translated)
    return (
      <p className="text-sm text-muted-foreground" data-testid="translation-pending">
        {t("translating")}
      </p>
    );
  if ("error" in translated)
    return (
      <p className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground" role="alert">
        {translated.error}
        <Button size="xs" variant="outline" onClick={onRetry}>
          {t("retry")}
        </Button>
      </p>
    );
  return (
    <p lang="zh-CN" className="text-muted-foreground" data-testid="translation">
      {translated.text}
    </p>
  );
}

/**
 * The paragraph's sentences, each a run of words. An open analysis goes under its sentence,
 * splitting the paragraph there, so the text around it stays in `<p>`s (the word popup finds
 * a word's sentence in its `<p>`).
 */
function OriginalParagraph({
  text,
  analysing,
  open,
  onSentence,
  onRetry,
  shadowing,
}: {
  text: string;
  analysing: boolean;
  open: (sentence: number) => Analysis | undefined;
  onSentence: (sentence: number, text: string) => void;
  onRetry: (sentence: number, text: string) => void;
  shadowing?: { open: boolean; toggle: () => void };
}) {
  const t = useTranslations("speech.shadowing");
  const sentences = sentencesOf(text);
  const runs: { from: number; to: number }[] = [];
  let from = 0;
  sentences.forEach((_, s) => {
    if (open(s) || s === sentences.length - 1) {
      runs.push({ from, to: s + 1 });
      from = s + 1;
    }
  });
  const canShadow = shadowing && shadowingSentences(text).length > 0;

  return (
    <div className="flex items-start gap-1">
      <div className="min-w-0 flex-1">
        {runs.map((run) => {
          const last = sentences[run.to - 1];
          const analysis = open(run.to - 1);
          return (
            <Fragment key={run.from}>
              <p className="my-0">
                {sentences.slice(run.from, run.to).map((sentence, k) => {
                  const s = run.from + k;
                  return analysing ? (
                    <span
                      key={s}
                      role="button"
                      tabIndex={0}
                      aria-expanded={Boolean(open(s))}
                      data-sentence={s}
                      onClick={() => onSentence(s, sentence)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" || e.key === " ") {
                          e.preventDefault();
                          onSentence(s, sentence);
                        }
                      }}
                      className={cn(
                        "cursor-pointer rounded-sm transition-colors hover:bg-brand-soft focus-visible:bg-brand-soft focus-visible:outline-none",
                        open(s) && "bg-brand-soft",
                      )}
                    >
                      {sentence}
                    </span>
                  ) : (
                    <Words key={s} text={sentence} highlighted={Boolean(open(s))} />
                  );
                })}
              </p>
              {analysis && (
                <AnalysisCard
                  analysis={analysis}
                  onClose={() => onSentence(run.to - 1, last)}
                  onRetry={() => onRetry(run.to - 1, last)}
                />
              )}
            </Fragment>
          );
        })}
      </div>
      {canShadow && (
        <ShadowingButton
          compact
          open={shadowing.open}
          onToggle={shadowing.toggle}
          label={t("openParagraph")}
          className="mt-0.5 shrink-0"
        />
      )}
    </div>
  );
}

function Words({ text, highlighted }: { text: string; highlighted: boolean }) {
  return (
    <span className={cn(highlighted && "rounded-sm bg-brand-soft")}>
      {pieces(text).map((piece, i) =>
        piece.word ? (
          <span
            key={i}
            data-word={piece.text}
            className="cursor-pointer rounded-sm transition-colors hover:bg-brand-soft hover:ring-2 hover:ring-brand-soft"
          >
            {piece.text}
          </span>
        ) : (
          piece.text
        ),
      )}
    </span>
  );
}

function AnalysisCard({
  analysis,
  onClose,
  onRetry,
}: {
  analysis: Analysis;
  onClose: () => void;
  onRetry: () => void;
}) {
  const t = useTranslations("chat.workspace.reading");
  return (
    <section
      className="relative my-2 rounded-lg border bg-muted/40 px-4 py-3 text-[13.5px] leading-6"
      data-testid="sentence-analysis"
      aria-label={t("analysisLabel")}
    >
      <Button
        size="icon-xs"
        variant="ghost"
        className="absolute top-2 right-2"
        aria-label={t("closeAnalysis")}
        onClick={onClose}
      >
        <X />
      </Button>
      {analysis.status === "loading" ? (
        <p className="text-muted-foreground" role="status">
          {t("analysing")}
        </p>
      ) : analysis.status === "error" ? (
        <p className="flex flex-wrap items-center gap-2 pr-6 text-muted-foreground" role="alert">
          {analysis.error}
          <Button size="xs" variant="outline" onClick={onRetry}>
            {t("retry")}
          </Button>
        </p>
      ) : (
        <dl className="flex flex-col gap-2 pr-6">
          <Item label={t("meaning")}>
            <span lang="zh-CN">{analysis.data.meaning}</span>
          </Item>
          <Item label={t("main")}>
            <span lang="en">{analysis.data.main}</span>
          </Item>
          {analysis.data.clauses.length > 0 && (
            <Item label={t("clauses")}>
              <ul className="flex flex-col gap-0.5">
                {analysis.data.clauses.map((c) => (
                  <li key={c.text}>
                    <span lang="en" className="font-medium">
                      {c.text}
                    </span>
                    <span className="text-muted-foreground"> · {c.role}</span>
                  </li>
                ))}
              </ul>
            </Item>
          )}
          {analysis.data.phrases.length > 0 && (
            <Item label={t("phrases")}>
              <ul className="flex flex-col gap-0.5">
                {analysis.data.phrases.map((p) => (
                  <li key={p.text}>
                    <span lang="en" className="font-medium">
                      {p.text}
                    </span>
                    <span className="text-muted-foreground"> · {p.meaning}</span>
                  </li>
                ))}
              </ul>
            </Item>
          )}
          {analysis.data.tip && <Item label={t("tip")}>{analysis.data.tip}</Item>}
        </dl>
      )}
    </section>
  );
}

function Item({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <dt className="text-[11.5px] font-semibold text-muted-foreground">{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}
