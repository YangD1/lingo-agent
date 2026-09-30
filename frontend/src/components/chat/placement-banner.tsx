"use client";

import { X } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import { Button, buttonVariants } from "@/components/ui/button";
import { type BannerKind, bannerFor, fetchLatestPlacement } from "@/lib/placement";
import { usePlacementBannerClosed } from "@/lib/preferences";

const ACTIONS = { start: "startAction", resume: "resumeAction", retest: "retestAction" } as const;

/**
 * Invites the learner to the placement test (P1 plan §6.3): "take it" if they never did,
 * "continue" if one is left halfway, "retake it" once the last one is over 60 days old
 * (Q18e). Closing it is remembered in this browser, per kind.
 */
export function PlacementBanner() {
  const t = useTranslations("chat.placementBanner");
  const [kind, setKind] = useState<BannerKind | null>(null);
  // Closing a retest reminder silences it for that test only, not for later ones.
  const [closeKey, setCloseKey] = useState<string>("");
  const [closed, close] = usePlacementBannerClosed();

  useEffect(() => {
    fetchLatestPlacement().then(
      (latest) => {
        const next = bannerFor(latest);
        setKind(next);
        setCloseKey(next === "retest" ? `retest:${latest?.finished_at}` : (next ?? ""));
      },
      () => {}, // a hint only: say nothing rather than an error
    );
  }, []);

  if (kind === null || closed === closeKey) return null;
  return (
    <div
      className="mx-auto mt-3 flex w-full max-w-3xl items-center gap-3 rounded-lg border bg-muted/50 px-4 py-2 text-sm"
      data-testid="placement-banner"
    >
      <span className="flex-1">{t(kind)}</span>
      <Link href="/placement" className={buttonVariants({ size: "sm" })}>
        {t(ACTIONS[kind])}
      </Link>
      <Button size="icon-sm" variant="ghost" aria-label={t("close")} onClick={() => close(closeKey)}>
        <X />
      </Button>
    </div>
  );
}
