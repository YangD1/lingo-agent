"use client";

import { ChevronRight, Trash2 } from "lucide-react";
import { useFormatter, useLocale, useTranslations } from "next-intl";
import Link from "next/link";
import { useEffect, useId, useRef, useState } from "react";

import { AiBadge } from "@/components/ai-badge";
import { useDescribeError } from "@/components/settings/use-describe-error";
import { Button, buttonVariants } from "@/components/ui/button";
import {
  deleteEvidence,
  type Evidence,
  type EvidencePage,
  fetchEvidence,
  type KCStatus,
  kcName,
  practiceHref,
} from "@/lib/learner";
import { cn } from "@/lib/utils";

const STATE_BAR: Record<KCStatus["state"], string> = {
  weak: "bg-destructive",
  learning: "bg-amber-500",
  mastered: "bg-emerald-600",
};

/**
 * One grammar point: name, level, mastery (as a bar and in words), and on opening the
 * evidence behind it. Deleting a piece of evidence recomputes the mastery.
 */
export function KCItem({
  kc,
  initiallyOpen,
  onChanged,
}: {
  kc: KCStatus;
  initiallyOpen: boolean;
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
    if (!window.confirm(t("confirmDelete"))) return;
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
    <li ref={ref} className="py-2" data-testid={`kc-${kc.kc_id}`}>
      <button
        type="button"
        aria-expanded={open}
        aria-controls={detailsId}
        onClick={() => setOpen(!open)}
        className="flex w-full items-center gap-2 text-left"
      >
        <ChevronRight className={cn("size-4 shrink-0 transition-transform", open && "rotate-90")} />
        <span className="flex-1">
          <span className="font-medium">{kcName(kc, locale)}</span>{" "}
          <span className="text-xs text-muted-foreground">{kc.cefr}</span>
        </span>
        <span
          role="meter"
          aria-label={t("mastery")}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={percent}
          className="hidden h-2 w-24 overflow-hidden rounded-full bg-muted sm:block"
        >
          <span
            className={cn("block h-full", STATE_BAR[kc.state])}
            style={{ width: `${percent}%` }}
          />
        </span>
        <span className="w-28 text-right text-sm tabular-nums">
          {percent}% · {t(`states.${kc.state}`)}
        </span>
      </button>
      <p className="pl-6 text-xs text-muted-foreground">
        {t("counts", {
          mistakes: kc.mistakes,
          produced: kc.produce_correct,
          recognized: kc.recog_correct,
        })}
      </p>
      {open && (
        <div id={detailsId} className="mt-2 flex flex-col gap-2 pl-6 text-sm">
          <span className="inline-flex items-center gap-1.5 self-start">
            <Link
              href={practiceHref(kc.kc_id)}
              className={buttonVariants({ size: "sm", variant: "outline" })}
            >
              {t("practice")}
            </Link>
            <AiBadge feature="practice_start" />
          </span>
          {error && (
            <p role="alert" className="text-destructive">
              {error}
            </p>
          )}
          {page && page.evidence.length === 0 && (
            <p className="text-muted-foreground">{t("noEvidence")}</p>
          )}
          {page && page.evidence.length > 0 && (
            <ul className="flex flex-col divide-y" aria-label={t("evidence")}>
              {page.evidence.map((e) => {
                const chat = e.source === "chat";
                return (
                <li key={e.id} className="flex items-start gap-2 py-1.5">
                  <div className="flex flex-1 flex-col gap-0.5">
                    <p>
                      {e.source === "placement" ? (
                        <span>{t(e.correct ? "placementCorrect" : "placementWrong")}</span>
                      ) : e.correct ? (
                        <span>{t("usedCorrectly")}</span>
                      ) : (
                        <>
                          <span className="line-through">{e.original}</span>
                          {e.correction && <> → {e.correction}</>}
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
                          <Link href="/placement" className="underline-offset-2 hover:underline">
                            {t("fromPlacement")}
                          </Link>
                        </>
                      ) : e.conversation_id ? (
                        <>
                          {" · "}
                          <Link
                            href={`/chat?c=${e.conversation_id}`}
                            className="underline-offset-2 hover:underline"
                          >
                            {t("from", { title: e.conversation_title || t("untitled") })}
                          </Link>
                        </>
                      ) : (
                        e.source === "chat" && ` · ${t("conversationDeleted")}`
                      )}
                    </p>
                  </div>
                  <Button
                    size="icon-sm"
                    variant="ghost"
                    aria-label={t("delete")}
                    disabled={busy}
                    onClick={() => void remove(e)}
                  >
                    <Trash2 />
                  </Button>
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
