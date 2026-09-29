"use client";

import { BookPlus } from "lucide-react";
import { useTranslations } from "next-intl";
import { type RefObject, useEffect, useRef, useState } from "react";

import { useDescribeError } from "@/components/settings/use-describe-error";
import { addMine } from "@/lib/vocab";

/** One English word, maybe hyphenated or with an apostrophe (same rule as the backend's
 * collected words); phrases and other text get no button. */
const SINGLE_WORD = /^[A-Za-z]+(?:['’-][A-Za-z]+)*$/;
const RESULT_MS = 3000;

type Picked = { word: string; top: number; left: number };
type Result = { text: string; error: boolean; top: number; left: number };

/** The word selected inside one of the tutor's replies in `container`, if any. */
export function pickedWord(selection: Selection | null, container: HTMLElement): Picked | null {
  if (!selection || selection.rangeCount === 0 || selection.isCollapsed) return null;
  const word = selection.toString().trim();
  if (!SINGLE_WORD.test(word)) return null;
  const reply = (node: Node | null) => {
    const element = node instanceof Element ? node : node?.parentElement;
    const found = element?.closest('[data-role="assistant"] [data-slot="message"]');
    return found && container.contains(found) ? found : null;
  };
  const inside = reply(selection.anchorNode);
  if (!inside || inside !== reply(selection.focusNode)) return null;
  const rect = selection.getRangeAt(0).getBoundingClientRect();
  return { word: word.replace(/’/g, "'"), top: rect.bottom + 4, left: rect.left };
}

/**
 * Select a word in a tutor reply to put it on the word list (task 13). The button
 * appears below the selection; the result replaces it for a few seconds.
 */
export function SelectToAdd({ container }: { container: RefObject<HTMLElement | null> }) {
  const t = useTranslations("vocab.mine");
  const tChat = useTranslations("chat");
  const describe = useDescribeError();
  const [picked, setPicked] = useState<Picked | null>(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<Result | null>(null);
  const hideTimer = useRef<ReturnType<typeof setTimeout>>(undefined);

  useEffect(() => {
    const update = () => {
      if (container.current) setPicked(pickedWord(document.getSelection(), container.current));
    };
    document.addEventListener("selectionchange", update);
    // The button is placed in the viewport, so it follows the text when the list scrolls.
    window.addEventListener("scroll", update, true);
    window.addEventListener("resize", update);
    return () => {
      document.removeEventListener("selectionchange", update);
      window.removeEventListener("scroll", update, true);
      window.removeEventListener("resize", update);
    };
  }, [container]);

  useEffect(() => () => clearTimeout(hideTimer.current), []);

  const add = (at: Picked) => {
    setBusy(true);
    clearTimeout(hideTimer.current);
    addMine(at.word).then(
      (added) => {
        const word = added.card.word.word;
        const text = !added.added
          ? t("already", { word })
          : added.matched === "lemma"
            ? t("addedLemma", { word, typed: at.word })
            : t("added", { word });
        show({ text, error: false, top: at.top, left: at.left });
      },
      (e: unknown) => show({ text: describe(e), error: true, top: at.top, left: at.left }),
    );
  };
  const show = (shown: Result) => {
    setBusy(false);
    setResult(shown);
    document.getSelection()?.removeAllRanges();
    hideTimer.current = setTimeout(() => setResult(null), RESULT_MS);
  };

  // A new selection takes over from the last result.
  const at = picked;
  if (!at) {
    if (!result) return null;
    return (
      <p
        role={result.error ? "alert" : "status"}
        style={{ top: result.top, left: result.left }}
        className={
          "fixed z-50 max-w-xs rounded-md border bg-popover px-3 py-1.5 text-xs shadow-md " +
          (result.error ? "text-destructive" : "text-popover-foreground")
        }
      >
        {result.text}
      </p>
    );
  }
  return (
    <button
      type="button"
      style={{ top: at.top, left: at.left }}
      disabled={busy}
      // Keep the selection: a mousedown elsewhere would clear it before the click.
      onMouseDown={(e) => e.preventDefault()}
      onClick={() => add(at)}
      className="fixed z-50 flex items-center gap-1 rounded-md border bg-popover px-2 py-1 text-xs text-popover-foreground shadow-md hover:bg-accent disabled:opacity-50"
    >
      <BookPlus className="size-3.5" />
      {tChat("addWord", { word: at.word })}
    </button>
  );
}
