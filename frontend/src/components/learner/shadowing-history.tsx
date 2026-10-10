"use client";

import { Trash2 } from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";
import { useCallback, useEffect, useState } from "react";

import { useDescribeError } from "@/components/settings/use-describe-error";
import { ShadowingBadge } from "@/components/speech/shadowing-button";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { ErrorText } from "@/components/ui/error-text";
import { InlineConfirm } from "@/components/ui/inline-confirm";
import { Tag } from "@/components/ui/tag";
import {
  clearShadowing,
  deleteShadowing,
  fetchShadowing,
  gradeWord,
  GOOD_ACCURACY,
  POOR_ACCURACY,
  type ShadowingResult,
  useShadowingMode,
} from "@/lib/shadowing";
import { cn } from "@/lib/utils";

const scoreTone = (score: number) =>
  score >= GOOD_ACCURACY ? "text-success" : score >= POOR_ACCURACY ? "text-warning" : "text-destructive";

/**
 * The learner's shadowing readings (Q56d, Q57d), newest first: each can be deleted, or all
 * at once. Recordings were never kept; deleting a reading leaves the speaking ability and
 * word marks it gave, like other evidence. Nothing while there is neither a reading nor a
 * way to shadow.
 */
export function ShadowingHistory() {
  const t = useTranslations("learner.shadowing");
  const describe = useDescribeError();
  const format = useFormatter();
  const mode = useShadowingMode();
  const [items, setItems] = useState<ShadowingResult[] | null>(null);
  const [next, setNext] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(
    (before?: string) =>
      fetchShadowing(before).then(
        (page) => {
          setItems((shown) => (before ? [...(shown ?? []), ...page.items] : page.items));
          setNext(page.next_before);
          setError(null);
        },
        (e: unknown) => setError(describe(e)),
      ),
    // `describe` is new each render; loading doesn't depend on it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );

  useEffect(() => {
    void load();
  }, [load]);

  async function run(action: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (e) {
      setError(describe(e));
    } finally {
      setBusy(false);
    }
  }

  const remove = (id: string) =>
    run(async () => {
      await deleteShadowing(id);
      setItems((shown) => shown?.filter((item) => item.id !== id) ?? null);
    });

  const clear = () =>
    run(async () => {
      await clearShadowing();
      setItems([]);
      setNext(null);
    });

  if (!mode && (items === null || items.length === 0) && !error) return null;

  return (
    <Card data-testid="learner-shadowing">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          {t("title")}
          <ShadowingBadge />
        </CardTitle>
        <CardDescription>{t("description")}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {error && <ErrorText>{error}</ErrorText>}
        {items && items.length === 0 && (
          <p className="text-sm text-muted-foreground">{t("empty")}</p>
        )}
        {items && items.length > 0 && (
          <>
            <ul className="flex flex-col divide-y border-b text-[13px]" aria-label={t("title")}>
              {items.map((item) => (
                <li key={item.id} className="flex min-h-11 items-center gap-3 py-2" data-testid="shadowing-item">
                  <Score item={item} />
                  <div className="min-w-0 flex-1">
                    <p lang="en" className="truncate" title={item.reference_text}>
                      {item.reference_text}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      {format.dateTime(new Date(item.created_at), {
                        dateStyle: "medium",
                        timeStyle: "short",
                      })}
                      {" · "}
                      {t(`sources.${item.source}`)}
                      {offWords(item).length > 0 &&
                        ` · ${t("offWords", { words: offWords(item).join(", ") })}`}
                    </p>
                  </div>
                  <InlineConfirm question={t("confirmDelete")} onConfirm={() => void remove(item.id)} compact>
                    {(ask) => (
                      <Button
                        size="icon-xs"
                        variant="ghost"
                        aria-label={t("delete")}
                        disabled={busy}
                        onClick={ask}
                        className="shrink-0 text-muted-foreground hover:text-destructive"
                      >
                        <Trash2 />
                      </Button>
                    )}
                  </InlineConfirm>
                </li>
              ))}
            </ul>
            <div className="flex flex-wrap items-center gap-2">
              {next && (
                <Button size="sm" variant="outline" disabled={busy} onClick={() => void run(() => load(next))}>
                  {t("more")}
                </Button>
              )}
              <ConfirmDialog
                trigger={
                  <Button size="sm" variant="destructive" disabled={busy} className="ml-auto">
                    <Trash2 />
                    {t("clear")}
                  </Button>
                }
                title={t("clear")}
                description={t("clearConfirm")}
                onConfirm={() => void clear()}
              />
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}

/** The words said wrong in this reading (assessed ones only: a transcript can't tell). */
const offWords = (item: ShadowingResult) =>
  item.scores ? [...new Set(item.words.filter((w) => gradeWord(w) === "poor").map((w) => w.word))] : [];

/** The overall score, or for a rough result how many of the words were heard. */
function Score({ item }: { item: ShadowingResult }) {
  const t = useTranslations("learner.shadowing");
  if (item.scores) {
    const overall = Math.round(item.scores.overall);
    return (
      <span
        className={cn("w-10 shrink-0 text-center text-base font-semibold tabular-nums", scoreTone(overall))}
        aria-label={t("overall", { score: overall })}
      >
        {overall}
      </span>
    );
  }
  const heard = item.words.filter((w) => gradeWord(w) !== "extra");
  return (
    <span className="flex w-10 shrink-0 flex-col items-center gap-0.5">
      <span className="text-xs tabular-nums">
        {heard.filter((w) => gradeWord(w) === "good").length}/{heard.length}
      </span>
      <Tag variant="outline" className="h-4 px-1 text-[10px]">
        {t("rough")}
      </Tag>
    </span>
  );
}
