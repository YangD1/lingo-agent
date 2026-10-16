"use client";

import {
  BookOpen,
  CalendarCheck,
  Compass,
  FilePen,
  Flag,
  PanelRight,
  PanelRightClose,
  PenLine,
  Settings2,
  Target,
  Undo2,
} from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import Link from "next/link";
import { type ReactNode, useState } from "react";

import { PlanEditor, roundMinutes, useItemLabel } from "@/components/plan/plan-editor";
import { PracticeChoices } from "@/components/practice/practice-choices";
import { QuizCard } from "@/components/chat/quiz-card";
import { useWorkspaceOpener } from "@/components/workspace/opener";
import { Button, buttonVariants } from "@/components/ui/button";
import { ErrorText } from "@/components/ui/error-text";
import { type ApiErrorLike, useErrorMessage } from "@/i18n/errors";
import { ApiError } from "@/lib/api";
import { type CardAction, LINK_HREFS, type LinkKind, type TutorCard } from "@/lib/cards";
import type { PlanCardParams, PlanChoice } from "@/lib/plan";
import { kcName } from "@/lib/learner";
import { cn } from "@/lib/utils";
import { chatUrl } from "@/lib/workspace";

type Decide = (card: TutorCard, action: CardAction, choice?: PlanChoice) => Promise<void>;

/** The cards the tutor showed on a turn, under its reply (ADR 0015 §4). */
export function TutorCards({
  cards,
  onDecide,
  conversationId = null,
  onAsk = null,
}: {
  cards: TutorCard[];
  onDecide: Decide;
  /** Away from the chat page, workspace cards link to this conversation there. */
  conversationId?: string | null;
  /** Sends a message as the learner (a quiz card's "go over it"); null while one can't be sent. */
  onAsk?: ((text: string) => void) | null;
}) {
  if (cards.length === 0) return null;
  return (
    <div className="mt-2.5 flex flex-col gap-2" data-testid="tutor-cards">
      {cards.map((card) => (
        <CardItem
          key={card.id}
          card={card}
          onDecide={onDecide}
          conversationId={conversationId}
          onAsk={onAsk}
        />
      ))}
    </div>
  );
}

const ICONS = {
  word_book: BookOpen,
  learning_goal: Flag,
  practice: Target,
  link: Compass,
  writing: PenLine,
  daily_plan: CalendarCheck,
  workspace: PanelRight,
  workspace_edit: FilePen,
  workspace_closed: PanelRightClose,
  workspace_auto: Settings2,
};

function CardItem({
  card,
  onDecide,
  conversationId,
  onAsk,
  nested = false,
}: {
  card: TutorCard;
  onDecide: Decide;
  conversationId: string | null;
  onAsk: ((text: string) => void) | null;
  /** Shown inside a withdrawn card: not a card of the turn itself. */
  nested?: boolean;
}) {
  if (card.status === "withdrawn") {
    return (
      <Withdrawn card={card}>
        {card.kind === "quiz" ? (
          <QuizTitle card={card} />
        ) : (
          <CardItem
            card={{ ...card, status: "info" }}
            onDecide={onDecide}
            conversationId={conversationId}
            onAsk={onAsk}
            nested
          />
        )}
      </Withdrawn>
    );
  }
  if (card.kind === "quiz") {
    // Questions need the card's full width: no icon column (ADR 0044 §4).
    return (
      <div
        className="rounded-lg border border-border/70 bg-card px-3.5 py-3 text-[13px] shadow-(--shadow-card)"
        data-testid="tutor-card"
        data-kind={card.kind}
        data-status={card.status}
      >
        <QuizCard card={card} onAsk={onAsk} />
      </div>
    );
  }
  const Icon = ICONS[card.kind as keyof typeof ICONS];
  if (!Icon) return null; // from a newer backend
  return (
    <div
      className="flex gap-3 rounded-lg border border-border/70 bg-card px-3.5 py-3 text-[13px] shadow-(--shadow-card)"
      data-testid={nested ? undefined : "tutor-card"}
      data-kind={card.kind}
      data-status={card.status}
    >
      <span
        aria-hidden
        className={cn(
          "flex size-8 shrink-0 items-center justify-center rounded-[9px] [&>svg]:size-4",
          card.status === "applied"
            ? "bg-[color-mix(in_oklab,var(--success)_13%,transparent)] text-success"
            : card.status === "declined" || card.status === "undone"
              ? "bg-muted text-muted-foreground"
              : "bg-brand-soft text-brand-soft-foreground",
        )}
      >
        <Icon />
      </span>
      <div className="flex min-w-0 flex-1 flex-col gap-2">
        {card.kind === "word_book" && <WordBook card={card} />}
        {card.kind === "learning_goal" && <Goal card={card} />}
        {(card.kind === "word_book" || card.kind === "learning_goal") && (
          <Decision card={card} onDecide={onDecide} />
        )}
        {card.kind === "practice" && <Practice card={card} />}
        {card.kind === "link" && <LinkCard card={card} />}
        {card.kind === "writing" && <WritingCard card={card} />}
        {card.kind === "daily_plan" && <DailyPlanCard card={card} onDecide={onDecide} />}
        {(card.kind === "workspace" || card.kind === "workspace_edit") && (
          <WorkspaceCard card={card} conversationId={conversationId} />
        )}
        {card.kind === "workspace_closed" && <WorkspaceClosed card={card} />}
        {card.kind === "workspace_auto" && (
          <>
            <WorkspaceAuto card={card} />
            <Decision card={card} onDecide={onDecide} />
          </>
        )}
      </div>
    </div>
  );
}

/**
 * A card the tutor took back (ADR 0049): one line with its reason; what it showed can be
 * looked at again, with nothing left to confirm.
 */
function Withdrawn({ card, children }: { card: TutorCard; children: ReactNode }) {
  const t = useTranslations("chat.cards.withdrawn");
  const [open, setOpen] = useState(false);
  return (
    <div
      className="flex flex-col gap-2 rounded-lg border border-dashed border-border px-3.5 py-2 text-[13px] text-muted-foreground"
      data-testid="tutor-card"
      data-kind={card.kind}
      data-status={card.status}
    >
      <div className="flex items-center gap-2">
        <Undo2 aria-hidden className="size-3.5 shrink-0" />
        <p className="min-w-0 flex-1">
          {card.withdrawn_reason ? t("reason", { reason: card.withdrawn_reason }) : t("title")}
        </p>
        <Button size="xs" variant="ghost" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
          {open ? t("hide") : t("show")}
        </Button>
      </div>
      {open && (
        <div className="opacity-70" data-testid="withdrawn-original">
          {children}
        </div>
      )}
    </div>
  );
}

/** What a withdrawn quiz card was on: its questions were never meant to be answered. */
function QuizTitle({ card }: { card: TutorCard }) {
  const t = useTranslations("chat.cards.quiz");
  const locale = useLocale();
  const kc = card.display.kc;
  const name = kc ? kcName(kc, locale) : String(card.params.kc_id);
  return <p>{t(card.params.purpose === "check" ? "titleCheck" : "titleQuiz", { kc: name })}</p>;
}

function WordBook({ card }: { card: TutorCard }) {
  const t = useTranslations("chat.cards");
  const locale = useLocale();
  const book = card.display.book;
  const name = book ? (locale.startsWith("zh") ? book.name_zh : book.name_en) : String(card.params.book_id);
  const daily = card.params.daily_new;
  return (
    <div>
      <p className="text-sm font-semibold">{t("wordBook.title", { book: name })}</p>
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
      <p className="text-sm font-semibold">{t("goal.title")}</p>
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

/** The tutor's plan for today (ADR 0027): adjustable until confirmed, then it replaces
 * the plan on the dashboard. */
function DailyPlanCard({ card, onDecide }: { card: TutorCard; onDecide: Decide }) {
  const t = useTranslations("chat.cards.plan");
  const label = useItemLabel();
  const params = card.params as PlanCardParams;
  const [choice, setChoice] = useState<PlanChoice>(params.choice);
  const kc = card.display.kc;
  return (
    <>
      <p className="text-sm font-semibold">{t("title")}</p>
      {card.status === "proposed" ? (
        <PlanEditor
          choice={choice}
          limits={params.limits}
          estimates={params.estimates}
          onChange={setChoice}
        />
      ) : (
        <ul className="list-disc pl-4 text-muted-foreground" data-testid="plan-card-items">
          {params.items.map((item) => (
            <li key={item.kind}>{label(item.kind, item.count, item.kind === "practice" ? kc : null)}</li>
          ))}
          {params.items.length === 0 && <li>{t("empty")}</li>}
          <li className="list-none text-xs">{t("minutes", { n: roundMinutes(params.minutes) })}</li>
        </ul>
      )}
      <Decision card={card} onDecide={onDecide} choice={choice} />
    </>
  );
}

/** Confirm or decline a proposal; undo it once applied. Nothing changes before "confirm". */
function Decision({
  card,
  onDecide,
  choice,
}: {
  card: TutorCard;
  onDecide: Decide;
  /** A daily plan card applied as adjusted on it. */
  choice?: PlanChoice;
}) {
  const t = useTranslations("chat.cards");
  const errorMessage = useErrorMessage();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiErrorLike | null>(null);
  const act = (action: CardAction) => {
    setBusy(true);
    setError(null);
    const decided =
      action === "apply" && choice ? onDecide(card, action, choice) : onDecide(card, action);
    decided.then(
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
          <span className="text-xs font-medium text-success">
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
        <ErrorText size="xs">{errorMessage(error)}</ErrorText>
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
      <p className="text-sm font-semibold">{t("practice.title", { kc: name })}</p>
      <PracticeChoices kcId={kcId} origin="card" />
    </>
  );
}

function LinkCard({ card }: { card: TutorCard }) {
  const t = useTranslations("chat.cards.link");
  const kind = card.params.kind as LinkKind;
  if (!(kind in LINK_HREFS)) return null; // from a newer backend
  return (
    <>
      <p className="text-sm font-semibold">{t(`${kind}.title`)}</p>
      <LiveNumbers kind={kind} live={card.live} />
      <div>
        <Link href={LINK_HREFS[kind]} className={buttonVariants({ size: "sm" })}>
          {t(`${kind}.action`)}
        </Link>
      </div>
    </>
  );
}

/** writing_coach's review of the learner's text, line by line on the writing page; on
 * the chat page the text can also be revised in the workspace (ADR 0043 §4). */
function WritingCard({ card }: { card: TutorCard }) {
  const t = useTranslations("chat.cards.writing");
  const workspace = useWorkspaceOpener();
  const [opening, setOpening] = useState(false);
  const id = Number(card.params.submission_id);

  async function revise() {
    if (!workspace) return;
    setOpening(true);
    try {
      await workspace.openFrom({ source: "writing", id });
    } finally {
      setOpening(false);
    }
  }

  return (
    <>
      <p className="text-sm font-semibold">{t("title")}</p>
      <p className="text-xs text-muted-foreground">{t("body")}</p>
      <div className="flex flex-wrap gap-2">
        <Link href={`/writing/${id}`} className={buttonVariants({ size: "sm" })}>
          {t("action")}
        </Link>
        {workspace && (
          <Button size="sm" variant="outline" disabled={opening} onClick={() => void revise()}>
            {t("workspace")}
          </Button>
        )}
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
    case "vocab_learn":
      text = t("newLeft", { left: n("new_left") });
      break;
  }
  return text ? (
    <p className="text-xs text-muted-foreground" data-testid="card-live">
      {text}
    </p>
  ) : null;
}

/** The tutor opened a document or proposed edits to one (ADR 0043 §5–6): open it beside the
 * chat. Away from the chat page there is no workspace to open it in: link to it there. */
function WorkspaceCard({
  card,
  conversationId,
}: {
  card: TutorCard;
  conversationId: string | null;
}) {
  const t = useTranslations("chat.cards");
  const workspace = useWorkspaceOpener();
  const title = String(card.params.title ?? "");
  const docId = String(card.params.doc_id);
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
      <p className="min-w-0 flex-1">
        {card.kind === "workspace"
          ? t("workspaceOpened", { title })
          : t("workspaceEdits", { title, n: Number(card.params.count ?? 0) })}
      </p>
      {workspace ? (
        <Button size="sm" variant="outline" onClick={() => workspace.open(docId)}>
          {card.kind === "workspace" ? t("workspaceOpen") : t("workspaceReview")}
        </Button>
      ) : (
        conversationId && (
          <Link
            href={chatUrl(conversationId, docId)}
            className={buttonVariants({ size: "sm", variant: "outline" })}
          >
            {t("workspaceOnChat")}
          </Link>
        )
      )}
    </div>
  );
}

/** The tutor closed the workspace at the learner's word (ADR 0045 §2): nothing was deleted. */
function WorkspaceClosed({ card }: { card: TutorCard }) {
  const t = useTranslations("chat.cards");
  const workspace = useWorkspaceOpener();
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
      <p className="min-w-0 flex-1">{t("workspaceClosed")}</p>
      {workspace && (
        <Button
          size="sm"
          variant="outline"
          onClick={() => workspace.open(String(card.params.doc_id))}
        >
          {t("workspaceReopen")}
        </Button>
      )}
    </div>
  );
}

/** The tutor turned opening the workspace by itself on or off (ADR 0045 §3); undo restores it. */
function WorkspaceAuto({ card }: { card: TutorCard }) {
  const t = useTranslations("chat.cards");
  return (
    <div className="flex flex-col gap-0.5">
      <p>{card.params.on ? t("workspaceAutoOn") : t("workspaceAutoOff")}</p>
      <p className="text-xs text-muted-foreground">{t("workspaceAutoHint")}</p>
    </div>
  );
}
