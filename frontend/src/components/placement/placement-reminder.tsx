"use client";

import { ClipboardCheck } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import { Button, buttonVariants } from "@/components/ui/button";
import { Callout } from "@/components/ui/callout";
import {
  dismissPlacementReminder,
  fetchPlacementReminder,
  type PlacementReminder as Reminder,
  type ReminderReason,
} from "@/lib/placement";
import { cn } from "@/lib/utils";

/**
 * Reminds the learner of the placement test, with the reason (task 50, Q50b): never
 * taken, left halfway, most of the current level learned, or the last one getting old.
 * "Not now" is kept on the server, so the chat page, the practice page and the tutor
 * all stay quiet about that reason for a while (Q50c, Q50e).
 */
export function PlacementReminder({
  reasons,
  where,
  className,
  "data-testid": testId = "placement-reminder",
}: {
  /** Only these reasons; all by default. */
  reasons?: readonly ReminderReason[];
  /** A page with its own wording: on the practice page, "never" says practising first is fine. */
  where?: "practice";
  className?: string;
  "data-testid"?: string;
}) {
  const t = useTranslations("placementReminder");
  const [reminder, setReminder] = useState<Reminder | null>(null);

  useEffect(() => {
    fetchPlacementReminder().then(
      setReminder,
      () => {}, // a hint only: say nothing rather than an error
    );
  }, []);

  if (reminder === null || reminder.snoozed) return null;
  if (reasons && !reasons.includes(reminder.reason)) return null;

  const notNow = () => {
    setReminder(null);
    dismissPlacementReminder(reminder.key).catch(() => {}); // hidden on this page anyway
  };
  return (
    <Callout
      tone="brand"
      icon={<ClipboardCheck aria-hidden />}
      className={cn("flex-wrap", className)}
      data-testid={testId}
      data-reason={reminder.reason}
      action={
        <div className="flex items-center gap-1">
          <Button variant="ghost" size="sm" onClick={notNow}>
            {t("notNow")}
          </Button>
          <Link href="/placement" className={buttonVariants({ size: "sm" })}>
            {t(`${reminder.reason}Action`)}
          </Link>
        </div>
      }
    >
      {t(where === "practice" && reminder.reason === "never" ? "practice.never" : reminder.reason, {
        days: reminder.days_since ?? 0,
        level: reminder.level ?? "",
        learned: reminder.learned ?? 0,
        total: reminder.total ?? 0,
      })}
    </Callout>
  );
}
