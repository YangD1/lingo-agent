"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useState } from "react";

import { useDescribeError } from "@/components/settings/use-describe-error";
import { Button, buttonVariants } from "@/components/ui/button";
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
  onChange,
}: {
  quiet?: boolean;
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
      <p role="alert" className="text-sm text-destructive">
        {error}
      </p>
    ) : null;
  }
  const canMark = offer.unavailable === null && offer.count > 0;
  if (quiet && !canMark && offer.marked === 0) return null;

  return (
    <div className="flex flex-col gap-2 rounded-lg border p-4 text-sm" data-testid="placement-known">
      {offer.unavailable === "no_book" && (
        <p>
          {t("noBook")}{" "}
          <Link href="/vocab" className="underline underline-offset-2">
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
            <Button size="sm" disabled={busy} onClick={() => void act(markPlacementKnown)}>
              {t("mark", { count: offer.count })}
            </Button>
          </div>
        </>
      )}
      {offer.marked > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          <span data-testid="placement-known-marked">{t("marked", { count: offer.marked })}</span>
          <Button
            size="sm"
            variant="outline"
            disabled={busy}
            onClick={() => void act(undoPlacementKnown)}
          >
            {t("undo")}
          </Button>
          <Link href="/vocab" className={buttonVariants({ size: "sm", variant: "ghost" })}>
            {t("toVocab")}
          </Link>
        </div>
      )}
      {error && (
        <p role="alert" className="text-destructive">
          {error}
        </p>
      )}
    </div>
  );
}
