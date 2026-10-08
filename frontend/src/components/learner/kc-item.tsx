"use client";

import {
  ChevronRight,
  Circle,
  CircleCheck,
  CircleX,
  GraduationCap,
  Trash2,
} from "lucide-react";
import { useFormatter, useLocale, useTranslations } from "next-intl";
import Link from "next/link";
import { useEffect, useId, useRef, useState } from "react";

import { PracticeChoices } from "@/components/practice/practice-choices";
import { useDescribeError } from "@/components/settings/use-describe-error";
import { Button } from "@/components/ui/button";
import { InlineConfirm } from "@/components/ui/inline-confirm";
import { ProgressBar } from "@/components/ui/progress";
import { CefrTag, Tag } from "@/components/ui/tag";
import {
  deleteEvidence,
  type Evidence,
  type EvidencePage,
  fetchEvidence,
  type KCStatus,
  kcName,
  learnedChecks,
  type MasteryGate,
  type RelatedKC,
} from "@/lib/learner";
import { cn } from "@/lib/utils";
import { ErrorText } from "@/components/ui/error-text";

export const STATE_BAR: Record<KCStatus["state"], string> = {
  weak: "bg-chart-3",
  learning: "bg-chart-2",
  mastered: "bg-chart-1",
};

/**
 * One grammar point: name, level, mastery (as a bar and in words), and on opening the
 * evidence behind it. Deleting a piece of evidence recomputes the mastery.
 */
export function KCItem({
  kc,
  gate,
  mastered,
  initiallyOpen,
  isListed,
  onJump,
  onChanged,
}: {
  kc: KCStatus;
  gate: MasteryGate;
  /** p_mastery a learned grammar point needs (thresholds.mastered). */
  mastered: number;
  initiallyOpen: boolean;
  /** Whether a grammar point is in the list too, to jump to it. */
  isListed: (kcId: string) => boolean;
  onJump: (kcId: string) => void;
  /** Evidence was deleted: the mastery needs reloading. */
  onChanged: () => void;
}) {
  const t = useTranslations("learner.kc");
  const locale = useLocale();
  const format = useFormatter();
  const describe = useDescribeError();
  const detailsId = useId();
  const ref = useRef<HTMLLIElement>(null);
  const [open, setOpen] = useState(initiallyOpen);
  const [page, setPage] = useState<EvidencePage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const percent = Math.round(kc.p_mastery * 100);
  const errorType = (type: string) => {
    const key = `errorTypes.${type}` as Parameters<typeof t>[0];
    return t.has(key) ? t(key) : type;
  };

  useEffect(() => {
    if (initiallyOpen) ref.current?.scrollIntoView({ block: "center" });
  }, [initiallyOpen]);

  useEffect(() => {
    if (!open) return;
    let live = true;
    fetchEvidence(kc.kc_id).then(
      (p) => live && setPage(p),
      (e: unknown) => live && setError(describe(e)),
    );
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reload when opened or changed
  }, [open, kc.kc_id, kc.observations, kc.mistakes]);

  async function remove(item: Evidence) {
    setBusy(true);
    setError(null);
    try {
      await deleteEvidence(item.id);
      setPage((p) =>
        p && { evidence: p.evidence.filter((e) => e.id !== item.id), total: p.total - 1 },
      );
      onChanged();
    } catch (e) {
      setError(describe(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <li ref={ref} data-testid={`kc-${kc.kc_id}`}>
      <button
        type="button"
        aria-expanded={open}
        aria-controls={detailsId}
        onClick={() => setOpen(!open)}
        className="flex min-h-12 w-full items-center gap-2.5 py-3 text-left outline-none focus-visible:outline-2 focus-visible:outline-ring"
      >
        <ChevronRight
          className={cn(
            "size-4 shrink-0 text-muted-foreground transition-transform",
            open && "rotate-90",
          )}
        />
        <span className="flex min-w-0 flex-1 flex-col gap-1">
          <span className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-[550]">{kcName(kc, locale)}</span>
            <CefrTag level={kc.cefr} />
            {kc.mastered_at && (
              <Tag variant="success">
                <GraduationCap aria-hidden />
                {t("learnedTag")}
              </Tag>
            )}
          </span>
          <span className="text-xs text-muted-foreground">
            {t("counts", {
              mistakes: kc.mistakes,
              produced: kc.produce_correct,
              recognized: kc.recog_correct,
            })}
          </span>
        </span>
        <span className="flex w-28 shrink-0 flex-col items-end gap-1.5 sm:w-36">
          <span
            role="meter"
            aria-label={t("mastery")}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={percent}
            className="hidden w-full sm:block"
          >
            <ProgressBar value={kc.p_mastery} barClassName={STATE_BAR[kc.state]} />
          </span>
          <span className="text-xs text-muted-foreground tabular-nums">
            {percent}% · {t(`states.${kc.state}`)}
          </span>
        </span>
      </button>
      {open && (
        <div id={detailsId} className="flex flex-col gap-2 pb-3 pl-[26px] text-[13px]">
          <PracticeChoices kcId={kc.kc_id} origin="learner" className="self-start" />
          <LearnedProgress kc={kc} gate={gate} mastered={mastered} />
          {kc.prerequisites.length > 0 && (
            <Related label={t("prerequisites")} kcs={kc.prerequisites} isListed={isListed} onJump={onJump} />
          )}
          {kc.confusables.length > 0 && (
            <Related label={t("confusables")} kcs={kc.confusables} isListed={isListed} onJump={onJump} />
          )}
          {error && (
            <ErrorText>{error}</ErrorText>
          )}
          {page && page.evidence.length === 0 && (
            <p className="text-muted-foreground">{t("noEvidence")}</p>
          )}
          {page && page.evidence.length > 0 && (
            <ul className="flex flex-col divide-y divide-dashed" aria-label={t("evidence")}>
              {page.evidence.map((e) => {
                const chat = e.source === "chat";
                return (
                <li key={e.id} className="flex items-start gap-2 py-2">
                  {e.correct ? (
                    <CircleCheck aria-hidden className="mt-0.5 size-4 shrink-0 text-success" />
                  ) : (
                    <CircleX aria-hidden className="mt-0.5 size-4 shrink-0 text-destructive" />
                  )}
                  <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                    <p>
                      {e.source === "placement" ? (
                        <span>{t(e.correct ? "placementCorrect" : "placementWrong")}</span>
                      ) : e.correct && e.source === "exercise" ? (
                        <span>{t("practiceCorrect")}</span>
                      ) : e.correct ? (
                        <span>{t("usedCorrectly")}</span>
                      ) : (
                        <>
                          <span className="text-muted-foreground line-through decoration-destructive/70">
                            {e.original}
                          </span>
                          {e.correction && (
                            <>
                              {" → "}
                              <span className="font-[550] text-success">{e.correction}</span>
                            </>
                          )}
                        </>
                      )}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      {[
                        // A placement answer is only right or wrong: its type is a stand-in.
                        !e.correct && chat && e.error_type && errorType(e.error_type),
                        !e.correct && chat && e.severity && t(`severity.${e.severity}`),
                        e.l1_transfer && t("l1Transfer"),
                        !e.counted && t("notCounted"),
                        format.dateTime(new Date(e.created_at), {
                          dateStyle: "medium",
                          timeStyle: "short",
                        }),
                      ]
                        .filter(Boolean)
                        .join(" · ")}
                      {e.source === "placement" ? (
                        <>
                          {" · "}
                          <Link href="/placement" className="text-primary underline-offset-2 hover:underline">
                            {t("fromPlacement")}
                          </Link>
                        </>
                      ) : e.conversation_id ? (
                        <>
                          {" · "}
                          <Link
                            href={`/chat?c=${e.conversation_id}`}
                            className="text-primary underline-offset-2 hover:underline"
                          >
                            {t("from", { title: e.conversation_title || t("untitled") })}
                          </Link>
                        </>
                      ) : e.source === "exercise" ? (
                        ` · ${t("fromPractice")}`
                      ) : (
                        e.source === "chat" && ` · ${t("conversationDeleted")}`
                      )}
                    </p>
                  </div>
                  <InlineConfirm question={t("confirmDelete")} onConfirm={() => void remove(e)}>
                    {(ask) => (
                      <Button
                        size="icon-sm"
                        variant="ghost"
                        aria-label={t("delete")}
                        disabled={busy}
                        onClick={ask}
                      >
                        <Trash2 />
                      </Button>
                    )}
                  </InlineConfirm>
                </li>
                );
              })}
            </ul>
          )}
          {page && page.total > page.evidence.length && (
            <p className="text-xs text-muted-foreground">
              {t("olderHidden", { n: page.total - page.evidence.length })}
            </p>
          )}
        </div>
      )}
    </li>
  );
}

/** Grammar points linked in the grammar graph (ADR 0022); listed ones open on click. */
function Related({
  label,
  kcs,
  isListed,
  onJump,
}: {
  label: string;
  kcs: RelatedKC[];
  isListed: (kcId: string) => boolean;
  onJump: (kcId: string) => void;
}) {
  const locale = useLocale();
  return (
    <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs">
      <span className="text-muted-foreground">{label}</span>
      {kcs.map((k) =>
        isListed(k.kc_id) ? (
          <button
            key={k.kc_id}
            type="button"
            onClick={() => onJump(k.kc_id)}
            className="font-medium text-primary hover:underline"
          >
            {kcName(k, locale)}
          </button>
        ) : (
          <span key={k.kc_id} className="font-medium">
            {kcName(k, locale)}
          </span>
        ),
      )}
    </p>
  );
}

/** Learned: since when and the next review. Not yet: the four conditions, each met or not. */
function LearnedProgress({
  kc,
  gate,
  mastered,
}: {
  kc: KCStatus;
  gate: MasteryGate;
  mastered: number;
}) {
  const t = useTranslations("learner.kc.learned");
  const format = useFormatter();
  const date = (iso: string) => format.dateTime(new Date(iso), { dateStyle: "medium" });

  if (kc.mastered_at) {
    const dueNow = kc.due !== null && new Date(kc.due) <= new Date();
    return (
      <p data-testid="kc-learned" className="flex flex-wrap items-center gap-x-2 text-success">
        <GraduationCap aria-hidden className="size-4" />
        {t("done", { date: date(kc.mastered_at) })}
        {kc.due && (
          <span className="text-muted-foreground">
            · {dueNow ? t("dueNow") : t("due", { date: date(kc.due) })}
          </span>
        )}
      </p>
    );
  }
  return (
    <div data-testid="kc-learned-progress" className="flex flex-col gap-1">
      <p className="text-xs font-semibold text-muted-foreground">{t("title")}</p>
      <ul className="flex flex-col gap-0.5">
        {learnedChecks(kc, gate, mastered).map((check) => (
          <li key={check.key} className="flex items-center gap-1.5" data-met={check.met}>
            {check.met ? (
              <CircleCheck aria-hidden className="size-3.5 shrink-0 text-success" />
            ) : (
              <Circle aria-hidden className="size-3.5 shrink-0 text-muted-foreground" />
            )}
            <span className={check.met ? undefined : "text-muted-foreground"}>
              {check.key === "clean" && check.value === null
                ? t("cleanNever")
                : t(check.key, { value: check.value ?? 0, target: check.target })}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
