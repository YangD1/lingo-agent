"use client";

import { X } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import { Button, buttonVariants } from "@/components/ui/button";
import { bannerFor, fetchLatestPlacement } from "@/lib/placement";
import { usePlacementBannerClosed } from "@/lib/preferences";

/**
 * Invites the learner to the placement test until they finish one (P1 plan §6.3):
 * "take it" if they never did, "continue" if one is left halfway. Closing it is
 * remembered in this browser; retest reminders belong to the learning advice.
 */
export function PlacementBanner() {
  const t = useTranslations("chat.placementBanner");
  const [kind, setKind] = useState<"start" | "resume" | null>(null);
  const [closed, close] = usePlacementBannerClosed();

  useEffect(() => {
    fetchLatestPlacement().then(
      (latest) => setKind(bannerFor(latest)),
      () => {}, // a hint only: say nothing rather than an error
    );
  }, []);

  if (kind === null || closed === kind) return null;
  return (
    <div
      className="mx-auto mt-3 flex w-full max-w-3xl items-center gap-3 rounded-lg border bg-muted/50 px-4 py-2 text-sm"
      data-testid="placement-banner"
    >
      <span className="flex-1">{t(kind)}</span>
      <Link href="/placement" className={buttonVariants({ size: "sm" })}>
        {t(kind === "start" ? "startAction" : "resumeAction")}
      </Link>
      <Button size="icon-sm" variant="ghost" aria-label={t("close")} onClick={() => close(kind)}>
        <X />
      </Button>
    </div>
  );
}
