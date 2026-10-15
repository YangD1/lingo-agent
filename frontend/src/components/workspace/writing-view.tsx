"use client";

import { Check, CheckCheck, History, RotateCcw, SpellCheck2, X } from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import { AiBadge } from "@/components/ai-badge";
import { Button } from "@/components/ui/button";
import { ErrorText } from "@/components/ui/error-text";
import { Textarea } from "@/components/ui/textarea";
import { Failed, Pending, Review, useSubmission } from "@/components/writing/writing-review";
import { type ApiErrorLike, useErrorMessage } from "@/i18n/errors";
import { ApiError } from "@/lib/api";
import { DEFAULT_TUTOR, useTutor } from "@/lib/tutor";
import { cn } from "@/lib/utils";
import {
  type DiffPiece,
  decideEdit,
  type EditItem,
  getDoc,
  getVersion,
  isStale,
  listEdits,
  pendingItems,
  revertTo,
  saveText,
  type WorkspaceDocDetail,
  type WorkspaceEdit,
  type WorkspaceVersion,
  wordDiff,
} from "@/lib/workspace";
import { countWords, lengthProblem, submitWriting } from "@/lib/writing";

/** Typing stops this long → the text is saved (Q83f). */
export const SAVE_DELAY_MS = 2000;

const toApiErrorLike = (error: unknown): ApiErrorLike =>
  error instanceof ApiError ? error : { code: "network_error", message: String(error) };

type Saved = { version: number; text: string };

type Props = {
  doc: WorkspaceDocDetail;
  /** The document as a save, a decision or a revert returned it. */
  onDoc: (doc: WorkspaceDocDetail) => void;
  /** Goes up when the tutor proposes changes in the chat: list them again. */
  editsSignal: number;
};

/**
 * A writing document (ADR 0043 §5): typed into and saved on its own, reviewed like a
 * submission on /writing, with the tutor's proposed changes to accept or decline one by
 * one, and every version to look at and go back to.
 */
export function WritingView({ doc, onDoc, editsSignal }: Props) {
  const t = useTranslations("chat.workspace.writing");
  const errorMessage = useErrorMessage();
  const serverText = doc.content.text ?? "";
  const [text, setText] = useState(serverText);
  const [saved, setSaved] = useState<Saved>({ version: doc.version, text: serverText });
  // Another version came in (changes accepted, a revert, a reload): show it.
  if (doc.version !== saved.version) {
    setSaved({ version: doc.version, text: serverText });
    setText(serverText);
  }
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<{ error: ApiErrorLike; text: string } | null>(null);
  const [actionError, setActionError] = useState<ApiErrorLike | null>(null);
  const [busy, setBusy] = useState(false);
  const [edits, setEdits] = useState<WorkspaceEdit[]>([]);
  const [showVersions, setShowVersions] = useState(false);
  const [reviewId, setReviewId] = useState<number | null>(null);

  // The save and the unmount below read the latest values, not the render's.
  const latest = useRef({ text, saved, docId: doc.id, onDoc });
  useEffect(() => {
    latest.current = { text, saved, docId: doc.id, onDoc };
  });
  const inflight = useRef<Promise<boolean> | null>(null);

  /** Save what is typed now; true once the server has it (or had it already). */
  const save = useCallback((): Promise<boolean> => {
    const run = (): Promise<boolean> => {
      // One request at a time: after the one on the way, whatever was typed meanwhile.
      if (inflight.current) return inflight.current.then(run);
      const { text: sent, saved: base, docId } = latest.current;
      if (sent === base.text) return Promise.resolve(true);
      setSaving(true);
      const request = saveText(docId, base.version, sent).then(
        (fresh) => {
          const next = { version: fresh.version, text: sent };
          latest.current.saved = next;
          setSaved(next);
          setSaveError(null);
          latest.current.onDoc(fresh);
          return true;
        },
        (e: unknown) => {
          setSaveError({ error: toApiErrorLike(e), text: sent });
          return false;
        },
      );
      inflight.current = request.finally(() => {
        inflight.current = null;
        setSaving(false);
      });
      return inflight.current;
    };
    return run();
  }, []);

  // Typing stops → save; a failed text isn't sent again until it changes.
  const dirty = text !== saved.text;
  const failedHere = saveError?.text === text;
  useEffect(() => {
    if (!dirty || saving || failedHere) return;
    const timer = setTimeout(() => void save(), SAVE_DELAY_MS);
    return () => clearTimeout(timer);
  }, [text, dirty, saving, failedHere, save]);

  // Leaving the document (another one, closing the workspace) keeps what was typed.
  useEffect(
    () => () => {
      const { text: last, saved: base, docId } = latest.current;
      if (last !== base.text) void saveText(docId, base.version, last).catch(() => {});
    },
    [],
  );

  useEffect(() => {
    let live = true;
    listEdits(doc.id).then(
      (found) => live && setEdits(found),
      () => {},
    );
    return () => {
      live = false;
    };
  }, [doc.id, doc.version, editsSignal]);

  /** Save first, then act on the version the server has. */
  async function act(run: () => Promise<void>) {
    setBusy(true);
    setActionError(null);
    try {
      if (await save()) await run();
    } catch (e) {
      setActionError(toApiErrorLike(e));
    } finally {
      setBusy(false);
    }
  }

  const decide = (edit: WorkspaceEdit, accept: number[], decline: number[]) =>
    act(async () => {
      const { doc: fresh, edit: decided } = await decideEdit(edit.id, accept, decline);
      setEdits((all) => all.map((e) => (e.id === decided.id ? decided : e)));
      onDoc(fresh);
    });

  /** Every change that can still be accepted, one request per proposal. */
  const acceptAll = () =>
    act(async () => {
      for (const edit of edits) {
        const accept = edit.items
          .filter((i) => i.status === "pending" && !isStale(i.original, latest.current.text))
          .map((i) => i.index);
        if (accept.length === 0) continue;
        const { doc: fresh, edit: decided } = await decideEdit(edit.id, accept, []);
        setEdits((all) => all.map((e) => (e.id === decided.id ? decided : e)));
        onDoc(fresh);
        latest.current.text = fresh.content.text ?? "";
      }
    });

  const revert = (number: number) =>
    act(async () => {
      onDoc(await revertTo(doc.id, number));
      setShowVersions(false);
    });

  const reloadLatest = () =>
    act(async () => {
      setSaveError(null);
      const fresh = await getDoc(doc.id);
      setSaved({ version: fresh.version, text: fresh.content.text ?? "" });
      setText(fresh.content.text ?? "");
      onDoc(fresh);
    });

  const review = () =>
    act(async () => {
      setReviewId((await submitWriting(latest.current.text, "")).id);
    });

  const words = countWords(text);
  const tooFar = lengthProblem(text);
  const pending = pendingItems(edits);
  const acceptable = pending.filter(({ item }) => !isStale(item.original, text)).length;
  const conflict = saveError?.error.code === "workspace_version_conflict";

  return (
    <div className="flex flex-col gap-3" data-testid="writing-view">
      <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        <span className="tabular-nums">{t("words", { n: words })}</span>
        <span aria-hidden>·</span>
        <span role="status" data-testid="writing-save-status">
          {saving ? t("saving") : saveError ? t("notSaved") : dirty ? t("unsaved") : t("saved")}
        </span>
        <span className="flex-1" />
        <Button
          variant="ghost"
          size="sm"
          aria-expanded={showVersions}
          onClick={() => setShowVersions(!showVersions)}
          data-testid="writing-versions-toggle"
        >
          <History />
          {t("versions", { n: doc.versions.length })}
        </Button>
        <span className="inline-flex items-center gap-1">
          <Button
            size="sm"
            disabled={busy || tooFar !== null}
            title={tooFar ? t(`length.${tooFar}`) : undefined}
            onClick={() => void review()}
            data-testid="writing-review-button"
          >
            <SpellCheck2 />
            {t("review")}
          </Button>
          <AiBadge feature="writing_submit" />
        </span>
      </div>
      {saveError && (
        <ErrorText className="flex flex-wrap items-center gap-2">
          {conflict ? t("conflict") : errorMessage(saveError.error)}
          {conflict && (
            <Button variant="outline" size="sm" disabled={busy} onClick={() => void reloadLatest()}>
              {t("reload")}
            </Button>
          )}
        </ErrorText>
      )}
      {actionError && <ErrorText>{errorMessage(actionError)}</ErrorText>}
      {showVersions && (
        <Versions
          docId={doc.id}
          versions={doc.versions}
          current={doc.version}
          busy={busy}
          onRevert={(n) => void revert(n)}
        />
      )}
      {pending.length > 0 && (
        <PendingEdits
          pending={pending}
          text={text}
          acceptable={acceptable}
          busy={busy}
          onDecide={(edit, accept, decline) => void decide(edit, accept, decline)}
          onAcceptAll={() => void acceptAll()}
        />
      )}
      <Textarea
        aria-label={t("editor")}
        lang="en"
        spellCheck
        value={text}
        placeholder={t("placeholder")}
        onChange={(e) => setText(e.target.value)}
        className="min-h-64 bg-background text-[15px] leading-7 md:text-[15px]"
        data-testid="writing-editor"
      />
      {tooFar && <p className="text-xs text-muted-foreground">{t(`length.${tooFar}`)}</p>}
      {reviewId !== null && (
        <ReviewPanel key={reviewId} id={reviewId} onRetry={() => void review()} onClose={() => setReviewId(null)} />
      )}
    </div>
  );
}

/** The changes the tutor proposed, each with its reason, to accept or decline. */
function PendingEdits({
  pending,
  text,
  acceptable,
  busy,
  onDecide,
  onAcceptAll,
}: {
  pending: { edit: WorkspaceEdit; item: EditItem }[];
  text: string;
  acceptable: number;
  busy: boolean;
  onDecide: (edit: WorkspaceEdit, accept: number[], decline: number[]) => void;
  onAcceptAll: () => void;
}) {
  const t = useTranslations("chat.workspace.writing.edits");
  const name = useTutor()?.display_name ?? DEFAULT_TUTOR.display_name;
  return (
    <section
      aria-labelledby="workspace-edits-heading"
      className="flex flex-col gap-2 rounded-lg border border-border/70 bg-card p-3 shadow-(--shadow-card)"
      data-testid="workspace-edits"
    >
      <div className="flex items-center gap-2">
        <h3 id="workspace-edits-heading" className="flex-1 text-sm font-semibold">
          {t("heading", { name, n: pending.length })}
        </h3>
        {acceptable > 1 && (
          <Button size="sm" variant="outline" disabled={busy} onClick={onAcceptAll} data-testid="edit-accept-all">
            <CheckCheck />
            {t("acceptAll")}
          </Button>
        )}
      </div>
      <ol className="flex flex-col gap-2">
        {pending.map(({ edit, item }) => {
          const stale = isStale(item.original, text);
          return (
            <li
              key={`${edit.id}:${item.index}`}
              className="flex flex-col gap-1.5 rounded-md bg-muted/50 px-3 py-2 text-sm"
              data-testid="edit-item"
              data-stale={stale}
            >
              <p lang="en" className={cn("leading-relaxed", stale && "opacity-60")}>
                <Diff pieces={wordDiff(item.original, item.replacement)} />
              </p>
              {item.reason && <p className="text-xs text-muted-foreground">{item.reason}</p>}
              {stale && <p className="text-xs text-warning">{t("stale")}</p>}
              <div className="flex gap-1.5">
                <Button
                  size="sm"
                  variant="outline"
                  disabled={busy || stale}
                  onClick={() => onDecide(edit, [item.index], [])}
                  data-testid="edit-accept"
                >
                  <Check />
                  {t("accept")}
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={busy}
                  onClick={() => onDecide(edit, [], [item.index])}
                  data-testid="edit-decline"
                >
                  <X />
                  {t("decline")}
                </Button>
              </div>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

function Diff({ pieces }: { pieces: DiffPiece[] }) {
  const t = useTranslations("chat.workspace.writing.edits");
  return pieces.map((piece, i) =>
    piece.op === "same" ? (
      <span key={i}>{piece.text}</span>
    ) : piece.op === "del" ? (
      <del key={i} className="rounded-[3px] bg-destructive/10 text-destructive" aria-label={t("removed", { text: piece.text })}>
        {piece.text}
      </del>
    ) : (
      <ins key={i} className="rounded-[3px] bg-[color-mix(in_oklab,var(--success)_15%,transparent)] text-success no-underline" aria-label={t("added", { text: piece.text })}>
        {piece.text}
      </ins>
    ),
  );
}

/** Every version, newest first: look at one, go back to it (as a new version). */
function Versions({
  docId,
  versions,
  current,
  busy,
  onRevert,
}: {
  docId: string;
  versions: WorkspaceVersion[];
  current: number;
  busy: boolean;
  onRevert: (number: number) => void;
}) {
  const t = useTranslations("chat.workspace.writing.history");
  const format = useFormatter();
  const name = useTutor()?.display_name ?? DEFAULT_TUTOR.display_name;
  const [shown, setShown] = useState<{ number: number; text: string } | null>(null);
  const [error, setError] = useState<ApiErrorLike | null>(null);
  const errorMessage = useErrorMessage();

  function look(number: number) {
    if (shown?.number === number) return setShown(null);
    setError(null);
    getVersion(docId, number).then(
      (v) => setShown({ number, text: v.content.text ?? "" }),
      (e: unknown) => setError(toApiErrorLike(e)),
    );
  }

  return (
    <section
      aria-label={t("label")}
      className="flex flex-col gap-1 rounded-lg border border-border/70 bg-card p-2 text-sm"
      data-testid="writing-versions"
    >
      {[...versions].reverse().map((v) => (
        <div key={v.number} className="flex flex-col gap-1.5 rounded-md px-2 py-1.5" data-testid="writing-version">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <span className="font-medium">{t("number", { n: v.number })}</span>
            <span className="text-xs text-muted-foreground">
              {v.author === "tutor" ? name : t("me")}
              {" · "}
              {format.dateTime(new Date(v.updated_at), { dateStyle: "short", timeStyle: "short" })}
              {v.reverted_from !== null && ` · ${t("revertedFrom", { n: v.reverted_from })}`}
            </span>
            <span className="flex-1" />
            {v.number === current ? (
              <span className="text-xs text-muted-foreground">{t("current")}</span>
            ) : (
              <Button variant="ghost" size="sm" aria-expanded={shown?.number === v.number} onClick={() => look(v.number)}>
                {t("look")}
              </Button>
            )}
          </div>
          {shown?.number === v.number && (
            <div className="flex flex-col gap-2 rounded-md bg-muted/50 p-2.5">
              <p lang="en" className="max-h-48 overflow-y-auto text-[13px] leading-6 whitespace-pre-wrap" data-testid="writing-version-text">
                {shown.text}
              </p>
              <Button
                size="sm"
                variant="outline"
                className="self-start"
                disabled={busy}
                onClick={() => onRevert(v.number)}
                data-testid="writing-revert"
              >
                <RotateCcw />
                {t("revert")}
              </Button>
            </div>
          )}
        </div>
      ))}
      {error && <ErrorText className="px-2">{errorMessage(error)}</ErrorText>}
    </section>
  );
}

/** The review of what was sent, as on /writing, polled while it runs. */
function ReviewPanel({ id, onRetry, onClose }: { id: number; onRetry: () => void; onClose: () => void }) {
  const t = useTranslations("chat.workspace.writing");
  const { submission, error } = useSubmission(id);
  return (
    <section aria-label={t("reviewLabel")} className="flex flex-col gap-3" data-testid="writing-review-panel">
      <div className="flex items-center gap-2">
        <h3 className="flex-1 text-sm font-semibold">{t("reviewLabel")}</h3>
        <Link href={`/writing/${id}`} className="text-xs text-primary hover:underline">
          {t("reviewPage")}
        </Link>
        <Button variant="ghost" size="icon-sm" aria-label={t("closeReview")} title={t("closeReview")} onClick={onClose}>
          <X />
        </Button>
      </div>
      {error && <ErrorText>{error}</ErrorText>}
      {submission?.status === "pending" && <Pending />}
      {submission?.status === "failed" && (
        <Failed
          submission={submission}
          action={
            <Button size="sm" variant="outline" onClick={onRetry}>
              <RotateCcw />
              {t("retry")}
            </Button>
          }
        />
      )}
      {submission?.status === "done" && <Review submission={submission} />}
    </section>
  );
}
