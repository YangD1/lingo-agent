"use client";

import type { Scenario, SpeakingSessionDetail } from "@/lib/speaking";

/** A speaking practice's summary (task 59.5 fills it in). */
export function SpeakingSummaryView({
  detail,
}: {
  detail: SpeakingSessionDetail;
  scenario: Scenario | null;
  onChange: (detail: SpeakingSessionDetail) => void;
}) {
  return <div data-testid="speaking-summary" data-status={detail.status} />;
}
