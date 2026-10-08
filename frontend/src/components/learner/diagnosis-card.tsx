"use client";

import { ChevronRight, CircleX, GraduationCap, Trash2 } from "lucide-react";
import Link from "next/link";
import { useFormatter, useLocale, useTranslations } from "next-intl";
import { useId, useState } from "react";

import { AiBadge } from "@/components/ai-badge";
import { PracticeChoices } from "@/components/practice/practice-choices";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { ErrorText } from "@/components/ui/error-text";
import { CefrTag, Tag } from "@/components/ui/tag";
import {
  type CitedMistake,
  checkedSince,
  type DiagnosisPage,
  kcName,
  type RootCause,
} from "@/lib/learner";
import { cn } from "@/lib/utils";

/**
 * The tutor's diagnosis (P2 plan §6.2, task 47): the latest one that found something,
 * each root cause with the grammar points it lies in and the mistakes it cites. Before
 * the first one, a single line on when it comes.
 */
export function DiagnosisCard({
  page,
  error,
  busy,
  isListed,
  onJump,
  onDelete,
}: {
  page: DiagnosisPage | null;
  error: string | null;
  busy: boolean;
  /** Whether a grammar point is in the list below, to jump to it. */
  isListed: (kcId: string) => boolean;
  onJump: (kcId: string) => void;
  onDelete: (id: string) => void;
}) {
  const t = useTranslations("learner.diagnosis");
  const format = useFormatter();
  const date = (iso: string) => format.dateTime(new Date(iso), { dateStyle: "medium" });
  const d = page?.diagnosis ?? null;

  return (
    <Card data-testid="learner-diagnosis">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          {t("title")}
          <AiBadge feature="diagnosis" />
          {d && !d.boost_active && <Tag variant="outline">{t("older")}</Tag>}
        </CardTitle>
        <CardDescription>
          {page &&
            (d
              ? d.boost_active
                ? t("dated", { date: date(d.created_at), until: date(d.boost_until) })
                : t("datedOld", { date: date(d.created_at) })
              : !page.enabled
                ? t.rich("off", {
                    link: (chunks) => (
                      <Link href="/settings#background" className="text-primary hover:underline">
                        {chunks}
                      </Link>
                    ),
                  })
                : page.checked_at
                  ? t("nothingYet", { date: date(page.checked_at) })
                  : t("never"))}
        </CardDescription>
      </CardHeader>
      {(error || d) && (
        <CardContent className="flex flex-col gap-3">
          {error && <ErrorText>{error}</ErrorText>}
          {d && page && (
            <>
              {checkedSince(page) && page.checked_at && (
                <p className="text-xs text-muted-foreground">
                  {t("checkedSince", { date: date(page.checked_at) })}
                </p>
              )}
              {!page.enabled && (
                <p className="text-xs text-muted-foreground">
                  {t.rich("offNow", {
                    link: (chunks) => (
                      <Link href="/settings#background" className="text-primary hover:underline">
                        {chunks}
                      </Link>
                    ),
                  })}
                </p>
              )}
              <ol className="flex flex-col gap-3" aria-label={t("causes")}>
                {d.root_causes.map((cause, i) => (
                  <Cause key={i} cause={cause} isListed={isListed} onJump={onJump} />
                ))}
              </ol>
              <ConfirmDialog
                trigger={
                  <Button variant="ghost" size="sm" className="self-start" disabled={busy}>
                    <Trash2 />
                    {t("delete")}
                  </Button>
                }
                title={t("delete")}
                description={t("confirmDelete")}
                onConfirm={() => onDelete(d.id)}
              />
            </>
          )}
        </CardContent>
      )}
    </Card>
  );
}

function Cause({
  cause,
  isListed,
  onJump,
}: {
  cause: RootCause;
  isListed: (kcId: string) => boolean;
  onJump: (kcId: string) => void;
}) {
  const t = useTranslations("learner.diagnosis");
  const locale = useLocale();
  const listId = useId();
  const [open, setOpen] = useState(false);
  const missing = cause.cited - cause.evidence.length;
  // Practise where the cause lies: the root, unless it is learned already.
  const practise = cause.kcs.find((k) => !k.learned);

  return (
    <li className="flex flex-col gap-2 rounded-lg border p-3 text-[13px]" data-testid="diagnosis-cause">
      <p className="text-sm leading-relaxed">{cause.hypothesis}</p>
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="text-xs text-muted-foreground">{t("lies")}</span>
        {cause.kcs.map((k) =>
          isListed(k.kc_id) ? (
            <button
              key={k.kc_id}
              type="button"
              onClick={() => onJump(k.kc_id)}
              className="inline-flex items-center gap-1 text-xs font-medium text-primary hover:underline"
            >
              {kcName(k, locale)}
              <CefrTag level={k.cefr} />
            </button>
          ) : (
            <span key={k.kc_id} className="inline-flex items-center gap-1 text-xs font-medium">
              {kcName(k, locale)}
              <CefrTag level={k.cefr} />
            </span>
          ),
        )}
        {cause.kcs.some((k) => k.learned) && (
          <Tag variant="success">
            <GraduationCap aria-hidden />
            {t("someLearned")}
          </Tag>
        )}
        <Tag variant="outline">{t(`confidence.${cause.confidence}`)}</Tag>
      </div>
      <p>
        <span className="font-semibold">{t("suggestion")}</span>
        {cause.suggestion}
      </p>
      <div className="flex flex-wrap items-center gap-2">
        {practise && <PracticeChoices kcId={practise.kc_id} origin="learner" />}
        {cause.evidence.length > 0 && (
          <button
            type="button"
            aria-expanded={open}
            aria-controls={listId}
            onClick={() => setOpen(!open)}
            className="inline-flex items-center gap-1 text-xs font-medium text-primary hover:underline"
          >
            <ChevronRight className={cn("size-3.5 transition-transform", open && "rotate-90")} />
            {t("showEvidence", { n: cause.evidence.length })}
          </button>
        )}
        {missing > 0 && (
          <span className="text-xs text-muted-foreground">
            {cause.evidence.length === 0
              ? t("allDeleted", { n: cause.cited })
              : t("someDeleted", { n: cause.cited, m: missing })}
          </span>
        )}
      </div>
      {open && (
        <ul id={listId} className="flex flex-col divide-y divide-dashed" aria-label={t("evidence")}>
          {cause.evidence.map((e) => (
            <MistakeLine key={e.id} mistake={e} />
          ))}
        </ul>
      )}
    </li>
  );
}

function MistakeLine({ mistake: e }: { mistake: CitedMistake }) {
  const t = useTranslations("learner.diagnosis");
  const format = useFormatter();
  const when = format.dateTime(new Date(e.created_at), { dateStyle: "medium" });
  const link = "text-primary underline-offset-2 hover:underline";

  return (
    <li className="flex items-start gap-2 py-2">
      <CircleX aria-hidden className="mt-0.5 size-4 shrink-0 text-destructive" />
      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
        {e.source === "placement" ? (
          <p>{t("placementWrong")}</p>
        ) : (
          <p>
            <span className="text-muted-foreground line-through decoration-destructive/70">
              {e.original}
            </span>
            {e.correction && (
              <>
                {" → "}
                <span className="font-[550] text-success">{e.correction}</span>
              </>
            )}
          </p>
        )}
        <p className="text-xs text-muted-foreground">
          {when}
          {" · "}
          {e.source === "chat" && e.conversation_id ? (
            <Link href={`/chat?c=${e.conversation_id}`} className={link}>
              {t("from", { title: e.conversation_title || t("untitled") })}
            </Link>
          ) : e.source === "placement" ? (
            <Link href="/placement" className={link}>
              {t("sources.placement")}
            </Link>
          ) : (
            t(`sources.${e.source === "chat" ? "chatDeleted" : e.source}`)
          )}
        </p>
      </div>
    </li>
  );
}
