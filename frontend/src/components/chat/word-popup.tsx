"use client";

import { BookPlus, Volume2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { type RefObject, useCallback, useEffect, useRef, useState } from "react";

import { AiBadge } from "@/components/ai-badge";
import { useDescribeError } from "@/components/settings/use-describe-error";
import { ReadAloudBadge } from "@/components/speech/read-aloud-badge";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent } from "@/components/ui/popover";
import { ErrorText } from "@/components/ui/error-text";
import { speak, useCanSpeak } from "@/lib/speech";
import { type Example, type Lookup, addMine, fetchExamples, lookupWord } from "@/lib/vocab";
import { LingoCat } from "@/components/brand/lingo-cat";

/** Hovering this long over a word opens its popup (Q24i): passing over text opens nothing. */
export const HOVER_MS = 300;
// Time to move the mouse from the word into the popup before it closes.
const CLOSE_MS = 200;
const GLOSS_LINES = 3;
const BLOCKS = "p, li, blockquote, td, th, h1, h2, h3, h4, h5, h6";

/** The sentence a word is in, and where the word starts in it. */
export type Sentence = { text: string; at: number };

function endsSentence(text: string, i: number): boolean {
  const c = text[i];
  if ("。！？\n".includes(c)) return true;
  // "3.5" or "e.g.x" don't end a sentence; ". " does.
  return ".!?…".includes(c) && (i + 1 >= text.length || /[\s"'”’)]/.test(text[i + 1]));
}

/** The sentence around `span` (one of the message's words), cut from its paragraph. */
export function sentenceAround(span: Element): Sentence | null {
  const block = span.closest(BLOCKS) ?? span.closest('[data-slot="message"]');
  if (!block) return null;
  const range = document.createRange();
  range.setStart(block, 0);
  range.setEndBefore(span);
  const offset = range.toString().length;
  const all = block.textContent ?? "";
  let start = offset;
  while (start > 0 && !endsSentence(all, start - 1)) start--;
  let end = offset + (span.textContent ?? "").length;
  while (end < all.length && !endsSentence(all, end)) end++;
  const raw = all.slice(start, Math.min(end + 1, all.length));
  const lead = raw.length - raw.trimStart().length;
  return { text: raw.trim(), at: offset - start - lead };
}

const wordAt = (target: EventTarget | null) =>
  target instanceof Element ? target.closest<HTMLElement>("[data-word]") : null;

type Open = {
  id: number;
  anchor: HTMLElement;
  word: string;
  sentence: Sentence | null;
  /** Opened by a tap or click, or used: stays until dismissed instead of closing on mouse-out. */
  pinned: boolean;
};

/**
 * The word popup for the tutor's messages in `container` (ADR 0017 §2, Q24i): hover a word
 * for 0.3 s, or tap it, to see its entry, the sentence it's in, AI example sentences, and
 * to put it on the word list. Words are the `span[data-word]` that `<Markdown words>` makes.
 */
const HEADING = "mb-0.5 text-[11.5px] font-semibold text-muted-foreground";

export function WordPopup({ container }: { container: RefObject<HTMLElement | null> }) {
  const [open, setOpen] = useState<Open | null>(null);
  const openRef = useRef<Open | null>(null);
  const lastId = useRef(0);
  const openTimer = useRef<ReturnType<typeof setTimeout>>(undefined);
  const closeTimer = useRef<ReturnType<typeof setTimeout>>(undefined);
  // Each word is looked up once while the list is shown.
  const lookups = useRef(new Map<string, Promise<Lookup>>());

  const change = useCallback((next: Open | null) => {
    openRef.current = next;
    setOpen(next);
  }, []);

  const show = useCallback(
    (span: HTMLElement, pinned: boolean) => {
      clearTimeout(closeTimer.current);
      const current = openRef.current;
      if (current?.anchor === span) {
        if (pinned && !current.pinned) change({ ...current, pinned });
        return;
      }
      lastId.current += 1;
      change({
        id: lastId.current,
        anchor: span,
        word: (span.dataset.word ?? "").replace(/’/g, "'"),
        sentence: sentenceAround(span),
        pinned,
      });
    },
    [change],
  );

  const closeSoon = useCallback(() => {
    clearTimeout(closeTimer.current);
    closeTimer.current = setTimeout(() => {
      if (openRef.current && !openRef.current.pinned) change(null);
    }, CLOSE_MS);
  }, [change]);

  useEffect(() => {
    const el = container.current;
    if (!el) return;
    const over = (e: PointerEvent) => {
      const span = wordAt(e.target);
      if (!span || e.pointerType !== "mouse") return;
      clearTimeout(openTimer.current);
      if (openRef.current?.anchor === span) clearTimeout(closeTimer.current);
      else openTimer.current = setTimeout(() => show(span, false), HOVER_MS);
    };
    const out = (e: PointerEvent) => {
      if (!wordAt(e.target)) return;
      clearTimeout(openTimer.current);
      closeSoon();
    };
    const click = (e: MouseEvent) => {
      const span = wordAt(e.target);
      // A drag that selected text isn't a tap on the word.
      if (!span || document.getSelection()?.isCollapsed === false) return;
      clearTimeout(openTimer.current);
      show(span, true);
    };
    el.addEventListener("pointerover", over);
    el.addEventListener("pointerout", out);
    el.addEventListener("click", click);
    return () => {
      el.removeEventListener("pointerover", over);
      el.removeEventListener("pointerout", out);
      el.removeEventListener("click", click);
    };
  }, [container, show, closeSoon]);

  useEffect(
    () => () => {
      clearTimeout(openTimer.current);
      clearTimeout(closeTimer.current);
    },
    [],
  );

  const pin = () => {
    if (openRef.current && !openRef.current.pinned) change({ ...openRef.current, pinned: true });
  };

  return (
    <Popover
      open={open !== null}
      onOpenChange={(next) => {
        if (!next) change(null);
      }}
    >
      <PopoverContent
        anchor={open?.anchor}
        align="start"
        className="flex w-80 flex-col gap-2.5 text-[13px]"
        data-testid="word-popup"
        // Hover shouldn't take focus from the message box.
        initialFocus={false}
        finalFocus={false}
        onPointerEnter={() => clearTimeout(closeTimer.current)}
        onPointerLeave={(e) => e.pointerType === "mouse" && closeSoon()}
        onPointerDown={pin}
      >
        {open && (
          <WordCard
            key={open.id}
            word={open.word}
            sentence={open.sentence}
            lookup={(word) => {
              let found = lookups.current.get(word);
              if (!found) {
                found = lookupWord(word);
                lookups.current.set(word, found);
                // A failed lookup is tried again next time.
                found.catch(() => lookups.current.delete(word));
              }
              return found;
            }}
            onAdded={(word, entry) =>
              lookups.current.set(word, Promise.resolve({ ...entry, on_list: true }))
            }
          />
        )}
      </PopoverContent>
    </Popover>
  );
}

function WordCard({
  word,
  sentence,
  lookup,
  onAdded,
}: {
  word: string;
  sentence: Sentence | null;
  lookup: (word: string) => Promise<Lookup>;
  onAdded: (word: string, entry: Lookup) => void;
}) {
  const t = useTranslations("chat.word");
  const describe = useDescribeError();
  const speakable = useCanSpeak();
  const [entry, setEntry] = useState<Lookup | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [examples, setExamples] = useState<Example[] | null>(null);
  const [examplesBusy, setExamplesBusy] = useState(false);
  const [examplesError, setExamplesError] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [added, setAdded] = useState<string | null>(null);
  const [addError, setAddError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    lookup(word).then(
      (found) => live && setEntry(found),
      (e: unknown) => live && setError(describe(e)),
    );
    return () => {
      live = false;
    };
    // `lookup` and `describe` are new each render; the word is what matters.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [word]);

  const loadExamples = async (wordId: number) => {
    setExamplesBusy(true);
    setExamplesError(null);
    try {
      setExamples((await fetchExamples(wordId)).sentences);
    } catch (e) {
      setExamplesError(describe(e));
    } finally {
      setExamplesBusy(false);
    }
  };

  const add = async (found: Lookup) => {
    setAdding(true);
    setAddError(null);
    try {
      const result = await addMine(found.word.word);
      setAdded(result.added ? t("added") : t("onList"));
      onAdded(word, found);
    } catch (e) {
      setAddError(describe(e));
    } finally {
      setAdding(false);
    }
  };

  const header = (
    <div className="flex items-baseline gap-2">
      <span className="text-lg font-bold">{entry?.word.word ?? word}</span>
      {entry?.word.phonetic && (
        <span className="font-mono text-xs text-muted-foreground">/{entry.word.phonetic}/</span>
      )}
      {speakable && (
        <Button
          size="icon-xs"
          variant="ghost"
          className="self-center"
          aria-label={t("speak", { word: entry?.word.word ?? word })}
          onClick={() => speak(entry?.word.word ?? word)}
        >
          <Volume2 />
        </Button>
      )}
      {speakable && <ReadAloudBadge className="self-center" />}
    </div>
  );

  if (error)
    return (
      <>
        {header}
        <p role="alert" className="text-xs text-muted-foreground">
          {error}
        </p>
      </>
    );
  if (!entry)
    return (
      <>
        {header}
        <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <LingoCat size={16} label="" />
          {t("loading")}
        </p>
      </>
    );

  const glosses = entry.word.translation.split("\n").filter(Boolean).slice(0, GLOSS_LINES);
  return (
    <>
      {header}
      {entry.matched === "lemma" && (
        <p className="text-xs text-muted-foreground">{t("lemma", { word: entry.word.word })}</p>
      )}
      {glosses.length > 0 && (
        <ul className="space-y-0.5" data-testid="word-glosses">
          {glosses.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      )}
      {sentence && sentence.text !== word && (
        <section>
          <h4 className={HEADING}>{t("sentence")}</h4>
          <p data-testid="word-sentence">
            {sentence.text.slice(0, sentence.at)}
            <strong>{sentence.text.slice(sentence.at, sentence.at + word.length)}</strong>
            {sentence.text.slice(sentence.at + word.length)}
          </p>
        </section>
      )}
      <section>
        {examples ? (
          <>
            <h4 className={HEADING}>{t("examplesTitle")}</h4>
            <ul className="space-y-1.5 rounded-md bg-muted px-2.5 py-2" data-testid="word-examples">
              {examples.map((example) => (
                <li key={example.en}>
                  <p>{example.en}</p>
                  <p className="text-xs text-muted-foreground">{example.zh}</p>
                </li>
              ))}
            </ul>
          </>
        ) : (
          <div className="flex items-center gap-1.5">
            <Button
              size="xs"
              variant="outline"
              disabled={examplesBusy}
              onClick={() => void loadExamples(entry.word.id)}
            >
              {examplesBusy && <LingoCat mood="ai" size={16} label="" />}
              {examplesBusy ? t("examplesLoading") : t("examples")}
            </Button>
            <AiBadge feature="word_examples" />
          </div>
        )}
        {examplesError && (
          <ErrorText size="xs" className="mt-1">{examplesError}</ErrorText>
        )}
      </section>
      <div className="border-t pt-2.5">
        {entry.on_list || added ? (
          <p role="status" className="text-center text-xs text-success">
            {added ?? t("onList")}
          </p>
        ) : (
          <Button
            size="sm"
            variant="secondary"
            className="w-full"
            disabled={adding}
            onClick={() => void add(entry)}
          >
            <BookPlus />
            {t("add")}
          </Button>
        )}
        {addError && (
          <ErrorText size="xs" className="mt-1">{addError}</ErrorText>
        )}
      </div>
    </>
  );
}
