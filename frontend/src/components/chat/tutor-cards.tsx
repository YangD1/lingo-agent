"use client";

import { BookOpen, Compass, Flag, Target } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import Link from "next/link";
import { useState } from "react";

import { AiBadge } from "@/components/ai-badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { type ApiErrorLike, useErrorMessage } from "@/i18n/errors";
import { ApiError } from "@/lib/api";
import { type CardAction, LINK_HREFS, type LinkKind, type TutorCard } from "@/lib/cards";
import { practiceHref } from "@/lib/learner";

type Decide = (card: TutorCard, action: CardAction) => Promise<void>;

/** The cards the tutor showed on a turn, under its reply (ADR 0015 §4). */
export function TutorCards({ cards, onDecide }: { cards: TutorCard[]; onDecide: Decide }) {
  if (cards.length === 0) return null;
  return (
    <div className="mt-2 flex flex-col gap-2" data-testid="tutor-cards">
      {cards.map((card) => (
        <CardItem key={card.id} card={card} onDecide={onDecide} />
      ))}
    </div>
  );
}

const ICONS = { word_book: BookOpen, learning_goal: Flag, practice: Target, link: Compass };

function CardItem({ card, onDecide }: { card: TutorCard; onDecide: Decide }) {
  const Icon = ICONS[card.kind];
  return (
    <div
      className="flex gap-3 rounded-lg border bg-background p-3 text-sm"
      data-testid="tutor-card"
      data-kind={card.kind}
      data-status={card.status}
    >
      <Icon className="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-hidden />
      <div className="flex min-w-0 flex-1 flex-col gap-2">
        {card.kind === "word_book" && <WordBook card={card} />}
        {card.kind === "learning_goal" && <Goal card={card} />}
        {(card.kind === "word_book" || card.kind === "learning_goal") && (
          <Decision card={card} onDecide={onDecide} />
        )}
        {card.kind === "practice" && <Practice card={card} />}
        {card.kind === "link" && <LinkCard card={card} />}
      </div>
    </div>
  );
}

function WordBook({ card }: { card: TutorCard }) {
  const t = useTranslations("chat.cards");
  const locale = useLocale();
  const book = card.display.book;
  const name = book ? (locale.startsWith("zh") ? book.name_zh : book.name_en) : String(card.params.book_id);
  const daily = card.params.daily_new;
  return (
    <div>
      <p className="font-medium">{t("wordBook.title", { book: name })}</p>
      {typeof daily === "number" && (
        <p className="text-muted-foreground">{t("wordBook.daily", { n: daily })}</p>
      )}
    </div>
  );
}

function Goal({ card }: { card: TutorCard }) {
  const t = useTranslations("chat.cards");
  const tFields = useTranslations("memory.profile.fields");
  const tExams = useTranslations("memory.profile.exams");
  const { goal, target_exam: exam, daily_minutes: minutes } = card.params;
  const examName = (tag: string) => {
    const key = tag as Parameters<typeof tExams>[0];
    return tExams.has(key) ? tExams(key) : tag;
  };
  return (
    <div>
      <p className="font-medium">{t("goal.title")}</p>
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 text-muted-foreground">
        {typeof goal === "string" && (
          <>
            <dt>{tFields("goal")}</dt>
            <dd className="text-foreground">{goal}</dd>
          </>
        )}
        {typeof exam === "string" && (
          <>
            <dt>{tFields("target_exam")}</dt>
            <dd className="text-foreground">{examName(exam)}</dd>
          </>
        )}
        {typeof minutes === "number" && (
          <>
            <dt>{tFields("daily_minutes")}</dt>
            <dd className="text-foreground">{t("goal.minutes", { n: minutes })}</dd>
          </>
        )}
      </dl>
    </div>
  );
}

/** Confirm or decline a proposal; undo it once applied. Nothing changes before "confirm". */
function Decision({ card, onDecide }: { card: TutorCard; onDecide: Decide }) {
  const t = useTranslations("chat.cards");
  const errorMessage = useErrorMessage();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiErrorLike | null>(null);
  const act = (action: CardAction) => {
    setBusy(true);
    setError(null);
    onDecide(card, action).then(
      () => setBusy(false),
      (e: unknown) => {
        setBusy(false);
        setError(e instanceof ApiError ? e : { code: "network_error", message: String(e) });
      },
    );
  };
  return (
    <div className="flex flex-col gap-1">
      {card.status === "proposed" && (
        <div className="flex flex-wrap items-center gap-2">
          <Button size="sm" disabled={busy} onClick={() => act("apply")}>
            {t("apply")}
          </Button>
          <Button size="sm" variant="ghost" disabled={busy} onClick={() => act("decline")}>
            {t("decline")}
          </Button>
          <span className="text-xs text-muted-foreground">{t("pending")}</span>
        </div>
      )}
      {card.status === "applied" && (
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs font-medium text-emerald-700 dark:text-emerald-400">
            {t("applied")}
          </span>
          <Button size="sm" variant="outline" disabled={busy} onClick={() => act("undo")}>
            {t("undo")}
          </Button>
        </div>
      )}
      {card.status === "declined" && (
        <span className="text-xs text-muted-foreground">{t("declined")}</span>
      )}
      {card.status === "undone" && (
        <span className="text-xs text-muted-foreground">{t("undone")}</span>
      )}
      {error && (
        <p role="alert" className="text-xs text-destructive">
          {errorMessage(error)}
        </p>
      )}
    </div>
  );
}

function Practice({ card }: { card: TutorCard }) {
  const t = useTranslations("chat.cards");
  const locale = useLocale();
  const kc = card.display.kc;
  const kcId = String(card.params.kc_id);
  const name = kc ? `${locale.startsWith("zh") ? kc.name_zh : kc.name_en} (${kc.cefr})` : kcId;
  return (
    <>
      <p className="font-medium">{t("practice.title", { kc: name })}</p>
      <div className="flex items-center gap-2">
        <Link href={practiceHref(kcId)} className={buttonVariants({ size: "sm" })}>
          {t("practice.action")}
        </Link>
        <AiBadge feature="practice_start" />
      </div>
    </>
  );
}

function LinkCard({ card }: { card: TutorCard }) {
  const t = useTranslations("chat.cards.link");
  const kind = card.params.kind as LinkKind;
  if (!(kind in LINK_HREFS)) return null; // from a newer backend
  return (
    <>
      <p className="font-medium">{t(`${kind}.title`)}</p>
      <LiveNumbers kind={kind} live={card.live} />
      <div>
        <Link href={LINK_HREFS[kind]} className={buttonVariants({ size: "sm" })}>
          {t(`${kind}.action`)}
        </Link>
      </div>
    </>
  );
}

function LiveNumbers({ kind, live }: { kind: LinkKind; live?: Record<string, unknown> | null }) {
  const t = useTranslations("chat.cards.live");
  if (!live) return null;
  const n = (key: string) => (typeof live[key] === "number" ? (live[key] as number) : 0);
  let text: string | null = null;
  switch (kind) {
    case "vocab_review":
      text = t("review", { due: n("reviews_due"), left: n("new_left") });
      break;
    case "vocab_screen":
      text = live.screened ? t("screened") : t("notScreened");
      break;
    case "placement":
      if (live.in_progress) text = t("inProgress");
      else text = live.days_since == null ? t("never") : t("lastTest", { n: n("days_since") });
      break;
    case "learner":
      text = t("weak", { n: n("weak_kcs") });
      break;
  }
  return text ? (
    <p className="text-xs text-muted-foreground" data-testid="card-live">
      {text}
    </p>
  ) : null;
}
