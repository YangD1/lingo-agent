"use client";

import { ChevronRight } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import Link from "next/link";
import { useId, useState } from "react";

import {
  type Activity,
  type ContextRead,
  digest,
  type GrammarTags,
  type KCRef,
  type MemoryChanges,
  type MemoryRef,
} from "@/lib/activity";
import { learnerHref } from "@/lib/learner";
import { cn } from "@/lib/utils";

type Props = {
  activities: Activity[];
  memories: Record<string, MemoryRef>;
  kcs: Record<string, KCRef>;
  /** Background results are still expected. */
  waiting: boolean;
};

const STEP_NAMES = ["load_context", "reflect_memory", "grammar_tagging", "summarize"] as const;
type StepName = (typeof STEP_NAMES)[number];
const isStep = (name: string): name is StepName => (STEP_NAMES as readonly string[]).includes(name);

/** "What the tutor did" under a reply: one line, expandable (ADR 0013 §3). */
export function TurnActivity({ activities, memories, kcs, waiting }: Props) {
  const t = useTranslations("chat.activity");
  const [open, setOpen] = useState(false);
  const detailsId = useId();
  if (activities.length === 0 && !waiting) return null;

  const d = digest(activities);
  const parts = [
    d.memoriesRead > 0 && t("read", { n: d.memoriesRead }),
    d.memoriesSaved > 0 && t("saved", { n: d.memoriesSaved }),
    d.memoriesDeleted > 0 && t("deleted", { n: d.memoriesDeleted }),
    d.profileUpdated && t("profileUpdated"),
    d.mistakes > 0 && t("mistakes", { n: d.mistakes }),
    d.usedCorrectly > 0 && t("usedCorrectly", { n: d.usedCorrectly }),
    d.summaryUpdated && t("summaryUpdated"),
    d.failed.length + d.skipped.length > 0 && t("someFailed"),
    waiting && t("waiting"),
  ].filter((p): p is string => typeof p === "string");

  return (
    <div className="mt-1 px-1 text-xs text-muted-foreground">
      <button
        type="button"
        aria-expanded={open}
        aria-controls={detailsId}
        onClick={() => setOpen(!open)}
        className="flex items-center gap-1 text-left hover:text-foreground"
      >
        <ChevronRight className={cn("size-3 shrink-0 transition-transform", open && "rotate-90")} />
        <span>{t("line", { parts: parts.length ? parts.join(" · ") : t("nothing") })}</span>
      </button>
      {open && (
        <div id={detailsId} className="mt-1 flex flex-col gap-2 pl-4">
          {activities.map((a) => (
            <Step key={`${a.name}:${a.call_id}`} activity={a} memories={memories} kcs={kcs} />
          ))}
          <p className="flex gap-3">
            <Link href="/memory" className="underline hover:text-foreground">
              {t("manageMemory")}
            </Link>
            <Link href="/learner" className="underline hover:text-foreground">
              {t("learnerModel")}
            </Link>
            <Link href="/settings#display" className="underline hover:text-foreground">
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
}: {
  activity: Activity;
  memories: Record<string, MemoryRef>;
  kcs: Record<string, KCRef>;
}) {
  const t = useTranslations("chat.activity");
  const tProfile = useTranslations("memory.profile.fields");
  const locale = useLocale();
  if (!isStep(a.name)) return null; // from a newer backend
  const step = t(`steps.${a.name}`);
  if (a.status === "failed") return <p>{t("failed", { step })}</p>;
  if (a.status === "skipped") {
    return (
      <p>
        {t("skipped", { step })}{" "}
        <Link href="/settings" className="underline hover:text-foreground">
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
          <h4 className="font-medium">
            {ids.length ? t("readHeading", { n: ids.length }) : t("readNone")}
            {s.profile_items > 0 && ` · ${t("profileRead", { n: s.profile_items })}`}
          </h4>
          {ids.length > 0 && <ul className="list-disc pl-4">{ids.map(memory)}</ul>}
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
              <h4 className="font-medium">{t("savedHeading", { n: changed.length })}</h4>
              <ul className="list-disc pl-4">{changed.map(memory)}</ul>
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
              <h4 className="font-medium">{t("mistakesHeading", { n: s.mistakes.length })}</h4>
              <ul className="list-disc pl-4">
                {s.mistakes.map((m, i) => (
                  <li key={i}>
                    <span className="line-through">{m.original}</span>
                    {m.correction && <> → {m.correction}</>}
                    {" · "}
                    <Link
                      href={learnerHref(m.kc_id)}
                      className="text-muted-foreground/80 underline-offset-2 hover:text-foreground hover:underline"
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
    case "summarize":
      return <p>{t("summaryUpdated")}</p>;
  }
}
