"use client";

import { PlacementReminder } from "@/components/placement/placement-reminder";

/** The placement-test reminder on the chat page (P1 plan §6.3, task 50). */
export function PlacementBanner() {
  return (
    <PlacementReminder
      className="mx-auto mt-3 w-[calc(100%-1.5rem)] max-w-3xl"
      data-testid="placement-banner"
    />
  );
}
