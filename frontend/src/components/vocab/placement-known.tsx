"use client";

import { CircleCheck, Undo2 } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useState } from "react";

import { useDescribeError } from "@/components/settings/use-describe-error";
import { Button, buttonVariants } from "@/components/ui/button";
import { ErrorText } from "@/components/ui/error-text";
import { cn } from "@/lib/utils";
import {
  fetchPlacementKnown,
  markPlacementKnown,
  type PlacementKnown as Offer,
  undoPlacementKnown,
} from "@/lib/vocab";

/**
 * Offer to mark the current book's common words known, from the placement test's
 * vocabulary size (Q15c). Nothing changes until the learner confirms, and the whole
 * batch can be taken back. `quiet` shows nothing unless there is something to do:
 * the screening page uses it, the result page explains why nothing is offered.
 */
export function PlacementKnown({
  quiet = false,
  bare = false,
  onChange,
}: {
  quiet?: boolean;
  /** Inside a card already: no box of its own. */
  bare?: boolean;
  /** After marking or undoing: which words are left to screen has changed. */
  onChange?: () => void;
}) {
  const t = useTranslations("vocab.placementKnown");
  const describe = useDescribeError();
  const [offer, setOffer] = useState<Offer | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(
    () => fetchPlacementKnown().then(setOffer, (e: unknown) => setError(describe(e))),
    // eslint-disable-next-line react-hooks/exhaustive-deps -- describe is stable enough
    [],
  );

  useEffect(() => {
    void load();
  }, [load]);

  async function act(action: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await action();
      onChange?.();
      await load();
    } catch (e) {
      setError(describe(e));
    } finally {
      setBusy(false);
    }
  }

  if (offer === null) {
    return error && !quiet ? (
      <ErrorText>{error}</ErrorText>
    ) : null;
  }
  const canMark = offer.unavailable === null && offer.count > 0;
  if (quiet && !canMark && offer.marked === 0) return null;

  return (
    <div
      className={cn("flex flex-col gap-3 text-sm", !bare && "rounded-lg border bg-card p-4")}
      data-testid="placement-known"
    >
      {offer.unavailable === "no_book" && (
        <p>
          {t("noBook")}{" "}
          <Link href="/vocab" className="text-primary underline-offset-2 hover:underline">
            {t("chooseBook")}
          </Link>
        </p>
      )}
      {offer.unavailable === "unreliable" && <p>{t("unreliable")}</p>}
      {offer.unavailable === "no_placement" && <p>{t("noPlacement")}</p>}
      {offer.unavailable === null && !canMark && offer.marked === 0 && <p>{t("nothing")}</p>}
      {canMark && (
        <>
          <p>{t("offer", { count: offer.count })}</p>
          <div>
            <Button variant="outline" disabled={busy} onClick={() => void act(markPlacementKnown)}>
              {t("mark", { count: offer.count })}
            </Button>
          </div>
        </>
      )}
      {offer.marked > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          <span className="flex items-center gap-1.5 text-success">
            <CircleCheck aria-hidden className="size-4 shrink-0" />
            <span data-testid="placement-known-marked">{t("marked", { count: offer.marked })}</span>
          </span>
          <Button
            size="sm"
            variant="ghost"
            disabled={busy}
            onClick={() => void act(undoPlacementKnown)}
          >
            <Undo2 />
            {t("undo")}
          </Button>
          <Link href="/vocab" className={buttonVariants({ size: "sm", variant: "ghost" })}>
            {t("toVocab")}
          </Link>
        </div>
      )}
      {error && (
        <ErrorText>{error}</ErrorText>
      )}
    </div>
  );
}
