"use client";

import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import { TurnActivity } from "@/components/chat/turn-activity";
import { Tag } from "@/components/ui/tag";
import { type ConversationActivity, fetchActivity, type WordsCollected } from "@/lib/activity";
import { api, ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";
import { removeMine } from "@/lib/vocab";

/** While the call's reflection runs, how often its results are asked for. */
export const CALL_POLL_MS = 3000;

type Line = { id: string | null; role: "user" | "assistant"; content: string; interrupted: boolean };

/**
 * A realtime call after hanging up (task 62.5, Q62h): what both sides said (the tutor's
 * replies the learner cut short marked), then what the tutor did, on the call and after
 * it: words looked up and added (each can be taken off the word list again), memories
 * and grammar from the reflection. The reflection runs in the background, so this asks
 * again until it has finished.
 */
export function CallTranscript({ conversationId }: { conversationId: string }) {
  const t = useTranslations("speaking.callDetail");
  const [lines, setLines] = useState<Line[] | null>(null);
  const [activity, setActivity] = useState<ConversationActivity | null>(null);
  const [removed, setRemoved] = useState<Set<number>>(new Set());

  useEffect(() => {
    api<Line[]>(`/conversations/${conversationId}/messages`).then(setLines, () => setLines([]));
  }, [conversationId]);

  const pending = activity === null || activity.pending;
  useEffect(() => {
    if (!pending) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const load = async () => {
      try {
        const body = await fetchActivity(conversationId);
        if (stopped) return;
        setActivity(body);
        if (!body.pending) return;
      } catch {
        // asked again below
      }
      if (!stopped) timer = setTimeout(load, CALL_POLL_MS);
    };
    void load();
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [conversationId, pending]);

  // Words the tutor added, on the call or by reflection: are they still on the list?
  const wordsOnList: Record<number, boolean> = {};
  for (const a of activity?.activities ?? []) {
    if ((a.name !== "add_to_vocab" && a.name !== "vocab_collect") || a.status !== "ok") continue;
    for (const w of (a.summary as WordsCollected).added ?? []) {
      wordsOnList[w.word_id] = !removed.has(w.word_id) && activity!.words_on_list.includes(w.word_id);
    }
  }

  async function removeWord(wordId: number) {
    try {
      await removeMine(wordId);
    } catch (err) {
      if (!(err instanceof ApiError && err.status === 404)) throw err;
    }
    setRemoved((prev) => new Set(prev).add(wordId));
  }

  return (
    <section className="flex flex-col gap-3" aria-label={t("transcript")} data-testid="call-transcript">
      <h2 className="text-sm font-semibold">{t("transcript")}</h2>
      {lines !== null && lines.length === 0 && (
        <p className="text-sm text-muted-foreground">{t("noTranscript")}</p>
      )}
      {lines && lines.length > 0 && (
        <ol className="flex flex-col gap-2">
          {lines.map((line, i) => (
            <li
              key={line.id ?? i}
              data-role={line.role}
              lang="en"
              className={cn(
                "flex max-w-[85%] flex-col gap-1 px-3.5 py-2 text-sm shadow-(--shadow-card)",
                line.role === "user"
                  ? "self-end rounded-[18px_18px_6px_18px] bg-brand-soft text-brand-soft-foreground"
                  : "self-start rounded-[6px_18px_18px_18px] border border-border/70 bg-card",
              )}
            >
              <span>{line.content}</span>
              {line.interrupted && (
                <Tag variant="outline" className="self-start" lang={undefined}>
                  {t("interrupted")}
                </Tag>
              )}
            </li>
          ))}
        </ol>
      )}
      {lines && lines.length > 0 && (
        <p className="text-xs text-muted-foreground">{t("transcriptNote")}</p>
      )}
      {activity && (
        <TurnActivity
          activities={activity.activities}
          memories={activity.memories}
          kcs={activity.kcs}
          wordsOnList={wordsOnList}
          onRemoveWord={removeWord}
          waiting={activity.pending}
        />
      )}
    </section>
  );
}
