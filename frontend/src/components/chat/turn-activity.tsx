"use client";

import { ChevronRight } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import Link from "next/link";
import { useId, useState } from "react";

import {
  type Activity,
  type CardShown,
  type ContextRead,
  digest,
  type GrammarTags,
  type KCRef,
  type MemoryChanges,
  type MemoryRef,
  TOOL_NAMES,
  type WordsCollected,
} from "@/lib/activity";
import { learnerHref } from "@/lib/learner";
import { cn } from "@/lib/utils";

type Props = {
  activities: Activity[];
  memories: Record<string, MemoryRef>;
  kcs: Record<string, KCRef>;
  /** Whether each collected word is still on the word list (missing: assume it is). */
  wordsOnList?: Record<number, boolean>;
  onRemoveWord?: (wordId: number) => Promise<void>;
  /** Background results are still expected. */
  waiting: boolean;
};

type Words = Pick<Props, "wordsOnList" | "onRemoveWord">;

const STEP_NAMES = [
  "load_context",
  "reflect_memory",
  "grammar_tagging",
  "vocab_collect",
  "summarize",
  "tools",
  ...TOOL_NAMES,
] as const;
type StepName = (typeof STEP_NAMES)[number];
const isStep = (name: string): name is StepName => (STEP_NAMES as readonly string[]).includes(name);

/** "What the tutor did" under a reply: one line, expandable (ADR 0013 §3). */
const LIST = "flex list-disc flex-col gap-0.5 pl-4 marker:text-muted-foreground/60";
const FOOT_LINK = "font-medium text-primary underline-offset-2 hover:underline";

export function TurnActivity({ activities, memories, kcs, waiting, ...words }: Props) {
  const t = useTranslations("chat.activity");
  const [open, setOpen] = useState(false);
  const detailsId = useId();
  if (activities.length === 0 && !waiting) return null;

  const d = digest(activities);
  const parts = [
    d.practiced && t("practice"),
    d.planned && t("planning"),
    d.memoriesRead > 0 && t("read", { n: d.memoriesRead }),
    d.memoriesSaved > 0 && t("saved", { n: d.memoriesSaved }),
    d.memoriesDeleted > 0 && t("deleted", { n: d.memoriesDeleted }),
    d.profileUpdated && t("profileUpdated"),
    d.mistakes > 0 && t("mistakes", { n: d.mistakes }),
    d.usedCorrectly > 0 && t("usedCorrectly", { n: d.usedCorrectly }),
    d.wordsCollected > 0 && t("words", { n: d.wordsCollected }),
    d.cardsShown > 0 && t("cards", { n: d.cardsShown }),
    d.summaryUpdated && t("summaryUpdated"),
    d.failed.length + d.skipped.length > 0 && t("someFailed"),
    waiting && t("waiting"),
  ].filter((p): p is string => typeof p === "string");

  return (
    <div className="mt-2 text-[12.5px] text-muted-foreground">
      <button
        type="button"
        aria-expanded={open}
        aria-controls={detailsId}
        onClick={() => setOpen(!open)}
        className="-ml-1 flex items-center gap-1 rounded-full px-1.5 py-1 text-left transition-colors outline-none hover:bg-muted hover:text-foreground focus-visible:outline-2 focus-visible:outline-ring"
      >
        <ChevronRight className={cn("size-3.5 shrink-0 transition-transform", open && "rotate-90")} />
        <span>{t("line", { parts: parts.length ? parts.join(" · ") : t("nothing") })}</span>
      </button>
      {open && (
        <div
          id={detailsId}
          className="mt-1.5 flex flex-col gap-3 rounded-lg bg-[color-mix(in_oklab,var(--muted)_60%,var(--background))] px-3.5 py-3 text-[13px]"
        >
          {activities.map((a) => (
            <Step
              key={`${a.name}:${a.call_id}`}
              activity={a}
              memories={memories}
              kcs={kcs}
              {...words}
            />
          ))}
          <p className="flex gap-4 border-t pt-2.5 text-[12.5px]">
            <Link href="/memory" className={FOOT_LINK}>
              {t("manageMemory")}
            </Link>
            <Link href="/learner" className={FOOT_LINK}>
              {t("learnerModel")}
            </Link>
            <Link href="/settings#display" className="ml-auto hover:text-foreground">
              {t("hide")}
            </Link>
          </p>
        </div>
      )}
    </div>
  );
}

function Step({
  activity: a,
  memories,
  kcs,
  ...words
}: {
  activity: Activity;
  memories: Record<string, MemoryRef>;
  kcs: Record<string, KCRef>;
} & Words) {
  const t = useTranslations("chat.activity");
  const tProfile = useTranslations("memory.profile.fields");
  const locale = useLocale();
  if (!isStep(a.name)) return null; // from a newer backend
  const step = t(`steps.${a.name}`);
  if (a.kind === "tool") {
    if (a.status !== "ok") return <p>{t("toolFailed", { step })}</p>;
    const kind = (a.summary as CardShown).card_kind ?? "";
    const key = `cardKinds.${kind}` as Parameters<typeof t>[0];
    return <p>{t("cardShown", { card: t.has(key) ? t(key) : step })}</p>;
  }
  if (a.name === "tools") return <p>{t("toolsUnavailable")}</p>;
  if (a.status === "failed") return <p>{t("failed", { step })}</p>;
  if (a.status === "skipped") {
    return (
      <p>
        {t("skipped", { step })}{" "}
        <Link href="/settings" className={FOOT_LINK}>
          {t("goToSettings")}
        </Link>
      </p>
    );
  }

  const memory = (id: string) => (
    <li key={id}>{memories[id]?.content ?? <span className="italic">{t("memoryDeleted")}</span>}</li>
  );
  const profileField = (field: string) => {
    const key = field as Parameters<typeof tProfile>[0];
    return tProfile.has(key) ? tProfile(key) : field;
  };
  const kcName = (id: string) => {
    const kc = kcs[id];
    if (!kc) return id;
    return t("kc", { name: locale.startsWith("zh") ? kc.name_zh : kc.name_en, cefr: kc.cefr });
  };

  switch (a.name) {
    case "load_context": {
      const s = a.summary as ContextRead;
      const ids = [...(s.facts ?? []), ...(s.episodes ?? [])];
      return (
        <section>
          <h4 className="mb-1 text-[11.5px] font-[650] text-foreground">
            {ids.length ? t("readHeading", { n: ids.length }) : t("readNone")}
            {s.profile_items > 0 && ` · ${t("profileRead", { n: s.profile_items })}`}
          </h4>
          {ids.length > 0 && <ul className={LIST}>{ids.map(memory)}</ul>}
          {s.practice_kc && <p>{t("practiceRead", { kc: kcName(s.practice_kc) })}</p>}
          {s.planning && <p>{t("planningRead")}</p>}
        </section>
      );
    }
    case "reflect_memory": {
      const s = a.summary as MemoryChanges;
      const changed = [...(s.added ?? []), ...(s.updated ?? [])];
      if (!changed.length && !s.deleted && !s.profile_fields?.length) return null;
      return (
        <section>
          {changed.length > 0 && (
            <>
              <h4 className="mb-1 text-[11.5px] font-[650] text-foreground">{t("savedHeading", { n: changed.length })}</h4>
              <ul className={LIST}>{changed.map(memory)}</ul>
            </>
          )}
          {s.deleted > 0 && <p>{t("deleted", { n: s.deleted })}</p>}
          {s.profile_fields?.length > 0 && (
            <p>
              {t("profileFields", {
                fields: s.profile_fields.map(profileField).join(t("listSeparator")),
              })}
            </p>
          )}
        </section>
      );
    }
    case "grammar_tagging": {
      const s = a.summary as GrammarTags;
      if (!s.mistakes?.length && !s.used_correctly?.length) return null;
      return (
        <section>
          {s.mistakes?.length > 0 && (
            <>
              <h4 className="mb-1 text-[11.5px] font-[650] text-foreground">{t("mistakesHeading", { n: s.mistakes.length })}</h4>
              <ul className={LIST}>
                {s.mistakes.map((m, i) => (
                  <li key={i}>
                    <span className="line-through">{m.original}</span>
                    {m.correction && (
                      <>
                        {" → "}
                        <span className="font-medium text-success">{m.correction}</span>
                      </>
                    )}
                    {" · "}
                    <Link
                      href={learnerHref(m.kc_id)}
                      className="text-primary underline-offset-2 hover:underline"
                    >
                      {kcName(m.kc_id)}
                    </Link>
                  </li>
                ))}
              </ul>
            </>
          )}
          {s.used_correctly?.length > 0 && (
            <p>
              {t("usedCorrectlyList", {
                kcs: s.used_correctly.map(kcName).join(t("listSeparator")),
              })}
            </p>
          )}
        </section>
      );
    }
    case "vocab_collect": {
      const s = a.summary as WordsCollected;
      if (!s.added?.length && !s.existing?.length) return null;
      return (
        <section>
          {s.added?.length > 0 && (
            <>
              <h4 className="mb-1 text-[11.5px] font-[650] text-foreground">
                {t("wordsHeading")}{" "}
                <Link href="/vocab/mine" className="font-normal text-primary underline-offset-2 hover:underline">
                  {t("wordList")}
                </Link>
              </h4>
              <ul className={LIST}>
                {s.added.map((w) => (
                  <CollectedWordItem
                    key={w.word_id}
                    wordId={w.word_id}
                    word={w.word}
                    onList={words.wordsOnList?.[w.word_id] ?? true}
                    onRemove={words.onRemoveWord}
                  />
                ))}
              </ul>
            </>
          )}
          {s.existing?.length > 0 && (
            <p>
              {t("wordsExisting", {
                words: s.existing.map((w) => w.word).join(t("listSeparator")),
              })}
            </p>
          )}
        </section>
      );
    }
    case "summarize":
      return <p>{t("summaryUpdated")}</p>;
  }
}

function CollectedWordItem({
  wordId,
  word,
  onList,
  onRemove,
}: {
  wordId: number;
  word: string;
  onList: boolean;
  onRemove?: (wordId: number) => Promise<void>;
}) {
  const t = useTranslations("chat.activity");
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const remove = () => {
    if (!onRemove) return;
    setBusy(true);
    setFailed(false);
    onRemove(wordId).then(
      () => setBusy(false),
      () => {
        setBusy(false);
        setFailed(true);
      },
    );
  };
  return (
    <li>
      <span className={cn("font-medium text-foreground", !onList && "line-through opacity-60")}>
        {word}
      </span>{" "}
      {onList ? (
        onRemove && (
          <button
            type="button"
            onClick={remove}
            disabled={busy}
            aria-label={t("removeWordLabel", { word })}
            className="text-primary underline-offset-2 hover:underline disabled:opacity-50"
          >
            {t("removeWord")}
          </button>
        )
      ) : (
        <span>{t("wordRemoved")}</span>
      )}
      {failed && (
        <span role="alert" className="ml-2 text-destructive">
          {t("removeFailed")}
        </span>
      )}
    </li>
  );
}
