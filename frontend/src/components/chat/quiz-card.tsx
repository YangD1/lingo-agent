"use client";

import { CircleCheck, CircleX, ListChecks } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { useEffect, useRef, useState } from "react";

import { AiBadge } from "@/components/ai-badge";
import { CatLoading } from "@/components/brand/lingo-cat";
import { PracticeItem } from "@/components/practice/practice-item";
import { useDescribeError } from "@/components/settings/use-describe-error";
import { Button } from "@/components/ui/button";
import { ErrorText } from "@/components/ui/error-text";
import { ApiError } from "@/lib/api";
import type { TutorCard } from "@/lib/cards";
import { lessonChanged } from "@/lib/course";
import { kcName } from "@/lib/learner";
import {
  type Answered,
  answerItem,
  fetchSet,
  firstOpenId,
  type Item,
  itemPlace,
  type PracticeSet,
  reportItem,
} from "@/lib/practice";
import { DEFAULT_TUTOR, useTutor } from "@/lib/tutor";
import { petHappy } from "@/lib/tutor-pet";
import { cn } from "@/lib/utils";

/** How often a quiz still being written is polled. */
export const QUIZ_POLL_MS = 1500;

/** Items that count: shown and not reported. */
const counted = (set: PracticeSet) => set.items.filter((i) => i.status === "ok");

/** Right first answers over the items that count, as the backend scores it. */
export function quizScore(set: PracticeSet): { correct: number; total: number } {
  const items = counted(set);
  return { correct: items.filter((i) => i.result?.correct).length, total: items.length };
}

/** One line naming an item, for the summary. */
function questionText(item: Item): string {
  const c = item.content;
  return c.question ?? c.stem ?? c.source ?? c.original ?? (c.segments ?? []).join("");
}

/**
 * A quiz card in the chat (ADR 0044 §4): the tutor's `give_quiz` set, written in the
 * background, answered here one item at a time through the practice API, each with its
 * result at once, then a summary. Items show as soon as they are written (ADR 0048), so
 * the learner may wait for the next one between items. "Go over it" sends a fixed message as the learner, so
 * the tutor reviews it only when asked.
 */
export function QuizCard({
  card,
  onAsk,
}: {
  card: TutorCard;
  /** Sends the "go over it" message; absent while a reply is streaming or off the chat. */
  onAsk?: ((text: string) => void) | null;
}) {
  const t = useTranslations("chat.cards.quiz");
  const tStage = useTranslations("practice.stage");
  const tPractice = useTranslations("practice");
  const locale = useLocale();
  const describe = useDescribeError();
  const name = useTutor()?.display_name ?? DEFAULT_TUTOR.display_name;
  const setId = String(card.params.set_id);
  const purpose = card.params.purpose === "check" ? "check" : "quiz";
  const kc = card.display.kc;
  const passScore = card.display.pass_score ?? 0.8;

  const [set, setSet] = useState<PracticeSet | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [itemError, setItemError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const sending = useRef(false);
  // The item on show, by id: items written later may come before it. Null between
  // items while the rest are written, then for the summary.
  const [current, setCurrent] = useState<number | null>(null);

  /** A newer state of the set; the item on show stays, answered or not. */
  const lastStatus = useRef<PracticeSet["status"] | null>(null);
  const show = (next: PracticeSet) => {
    if (purpose === "quiz" && lastStatus.current === "generating" && next.status === "done") {
      lessonChanged(); // answered through while written: storing the rest finished it
    }
    lastStatus.current = next.status;
    setSet(next);
    setCurrent((id) =>
      id !== null && next.items.some((i) => i.id === id) ? id : firstOpenId(next),
    );
  };

  useEffect(() => {
    let live = true;
    fetchSet(setId).then(
      (next) => live && show(next),
      (e: unknown) => live && setError(describe(e)),
    );
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- once per set
  }, [setId]);

  const generating = set?.status === "generating";
  useEffect(() => {
    if (!generating) return;
    let live = true;
    const timer = setTimeout(() => {
      fetchSet(setId).then(
        (next) => live && show(next),
        (e: unknown) => live && setError(describe(e)),
      );
    }, QUIZ_POLL_MS);
    return () => {
      live = false;
      clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- re-armed by each new set state
  }, [generating, set, setId]);

  async function act(run: () => Promise<Answered>) {
    if (!set || sending.current) return;
    sending.current = true;
    setBusy(true);
    setItemError(null);
    try {
      const { item, set_done } = await run();
      setSet({ ...set, items: set.items.map((i) => (i.id === item.id ? item : i)) });
      if (purpose === "quiz" && set_done) lessonChanged();
      if (item.result?.correct) petHappy();
    } catch (e) {
      setItemError(describe(e));
      if (e instanceof ApiError && e.code === "not_answerable") {
        setCurrent(null);
        await fetchSet(set.id).then(show, () => undefined);
      }
    } finally {
      sending.current = false;
      setBusy(false);
    }
  }

  const kcLabel = kc ? kcName(kc, locale) : String(card.params.kc_id);
  const title = t(purpose === "check" ? "titleCheck" : "titleQuiz", { kc: kcLabel });
  const items = set ? counted(set) : [];
  const empty = set !== null && (set.status === "failed" || (!generating && items.length === 0));
  const shown = set?.items.find((i) => i.id === current);

  return (
    <div className="flex flex-col gap-3" data-testid="quiz-card" data-purpose={purpose} data-status={set?.status}>
      <div className="flex items-center gap-2">
        <span
          aria-hidden
          className="flex size-8 shrink-0 items-center justify-center rounded-[9px] bg-brand-soft text-brand-soft-foreground [&>svg]:size-4"
        >
          <ListChecks />
        </span>
        <p className="min-w-0 flex-1 text-sm font-semibold">{title}</p>
        <AiBadge feature="quiz_card" />
      </div>
      {error && <ErrorText size="xs">{error}</ErrorText>}
      {!set && !error && <CatLoading size={40} label={t("loading")} />}
      {generating && !shown && (
        <div data-testid="quiz-generating">
          <CatLoading
            mood="hop"
            size={48}
            label={items.length > 0 ? tPractice("waitingNext") : tStage(set?.stage ?? "generating")}
          />
        </div>
      )}
      {empty && (
        <p className="text-muted-foreground" data-testid="quiz-failed">
          {t("failed", { name })}
        </p>
      )}
      {set && !empty && shown && (
        <PracticeItem
          key={shown.id}
          item={shown}
          {...itemPlace(set, shown)}
          busy={busy}
          error={itemError}
          shortcuts={false}
          onAnswer={(reply, ms) => void act(() => answerItem(shown.id, reply, ms))}
          onReport={() => void act(() => reportItem(shown.id))}
          onNext={() => {
            setItemError(null);
            setCurrent(firstOpenId(set));
          }}
        />
      )}
      {set && !generating && !empty && !shown && (
        <Summary
          set={set}
          purpose={purpose}
          passScore={passScore}
          name={name}
          onAsk={onAsk ? () => onAsk(t("askMessage")) : null}
        />
      )}
    </div>
  );
}

function Summary({
  set,
  purpose,
  passScore,
  name,
  onAsk,
}: {
  set: PracticeSet;
  purpose: "check" | "quiz";
  passScore: number;
  name: string;
  onAsk: (() => void) | null;
}) {
  const t = useTranslations("chat.cards.quiz");
  const [asked, setAsked] = useState(false);
  const { correct, total } = quizScore(set);
  const passed = total > 0 && correct / total >= passScore;
  return (
    <div className="flex flex-col gap-2.5" data-testid="quiz-summary" data-passed={purpose === "quiz" ? passed : undefined}>
      <p className="flex items-center gap-1.5 font-semibold">
        {purpose === "check" ? (
          t("checkDone")
        ) : (
          <>
            {passed ? (
              <CircleCheck aria-hidden className="size-4 text-success" />
            ) : (
              <CircleX aria-hidden className="size-4 text-destructive" />
            )}
            {t(passed ? "passed" : "notPassed")}
          </>
        )}
        <span className="font-normal text-muted-foreground">
          {" · "}
          {t("score", { correct, total })}
        </span>
      </p>
      {purpose === "quiz" && (
        <p className="text-xs text-muted-foreground">
          {t(passed ? "passedNote" : "notPassedNote", { pct: Math.round(passScore * 100) })}
        </p>
      )}
      <ol className="flex flex-col gap-1">
        {counted(set).map((item) => (
          <li key={item.id} className="flex items-start gap-1.5" data-correct={item.result?.correct}>
            {item.result?.correct ? (
              <CircleCheck aria-label={t("right")} className="mt-0.5 size-3.5 shrink-0 text-success" />
            ) : (
              <CircleX aria-label={t("wrong")} className="mt-0.5 size-3.5 shrink-0 text-destructive" />
            )}
            <span className={cn("min-w-0 truncate", !item.result?.correct && "text-muted-foreground")}>
              {questionText(item)}
            </span>
          </li>
        ))}
      </ol>
      {onAsk && (
        <div className="flex items-center gap-2">
          <Button
            size="sm"
            variant="outline"
            disabled={asked}
            onClick={() => {
              setAsked(true);
              onAsk();
            }}
          >
            {t("ask", { name })}
          </Button>
          <AiBadge feature="chat_message" />
        </div>
      )}
    </div>
  );
}
