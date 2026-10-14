"use client";

import { useLocale } from "next-intl";
import { useCallback, useEffect, useRef } from "react";

import type { Advice } from "@/lib/advice";
import {
  afterReviewNudge,
  mayNudge,
  type Nudge,
  noteSaid,
  pickNudge,
  PLAN_DONE_NUDGE,
  readLog,
  SETTLE_MS,
  typing,
} from "@/lib/pet-nudges";
import type { Plan } from "@/lib/plan";
import { useOnPlanDone, usePetState } from "@/lib/tutor-pet";
import { useOnReviewed } from "@/lib/vocab";

/**
 * When the desk pet reminds (ADR 0039 §4): a while after arriving on a page, after a round
 * of flashcards, when woken from a doze, and when today's plan is done. Nothing while `on`
 * is false (the learner's switch) or while `quiet` (flashcards, the chat window, a bubble
 * already up, a call, the pet talking or listening). `show` puts the bubble up.
 */
export function usePetNudges({
  on,
  advice,
  plan,
  pathname,
  quiet,
  show,
}: {
  on: boolean;
  advice: Advice | null;
  plan: Plan | null;
  pathname: string;
  quiet: boolean;
  show: (nudge: Nudge) => void;
}) {
  const locale = useLocale();
  const state = usePetState();

  const say = useCallback(
    (nudge: Nudge | null, event: boolean) => {
      if (!nudge || typing()) return;
      const log = readLog();
      if (log.said.includes(nudge.id)) return;
      if (nudge !== PLAN_DONE_NUDGE && !mayNudge(log, Date.now(), event)) return;
      noteSaid(nudge);
      show(nudge);
    },
    [show],
  );

  // Settled on a page: the best thing to suggest, if it is time.
  useEffect(() => {
    if (!on || quiet) return;
    const timer = setTimeout(() => {
      say(pickNudge({ advice, plan, pathname, said: readLog().said, locale }), false);
    }, SETTLE_MS);
    return () => clearTimeout(timer);
  }, [on, quiet, advice, plan, pathname, locale, say]);

  // A flashcards round closed: once the advice is loaded again, maybe new words next.
  const reviewed = useRef(false);
  useOnReviewed(
    useCallback(() => {
      reviewed.current = true;
    }, []),
  );
  useEffect(() => {
    if (!reviewed.current || !advice) return;
    reviewed.current = false;
    if (on && !quiet) say(afterReviewNudge(advice, readLog().said), true);
  }, [advice, on, quiet, say]);

  // Woken from a doze: welcome back, and the best thing to suggest.
  const was = useRef(state);
  useEffect(() => {
    const woke = was.current === "sleeping" && state !== "sleeping";
    was.current = state;
    if (!woke || !on || quiet) return;
    const nudge = pickNudge({ advice, plan, pathname, said: readLog().said, locale });
    say(nudge && { ...nudge, welcome: true }, true);
  }, [state, on, quiet, advice, plan, pathname, locale, say]);

  useOnPlanDone(
    useCallback(() => {
      if (on && !quiet) say(PLAN_DONE_NUDGE, true);
    }, [on, quiet, say]),
  );
}
