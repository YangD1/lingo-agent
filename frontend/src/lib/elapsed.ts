/** The longest time the API keeps for answering a card or an exercise (`le=3_600_000`). */
export const MAX_ELAPSED_MS = 3_600_000;

/**
 * How long an answer took, as sent with it; undefined when it is no measure of answering,
 * such as a card left open while the learner was away, so the answer still goes through.
 */
export function elapsedMs(ms: number | undefined): number | undefined {
  if (ms === undefined || !Number.isFinite(ms)) return undefined;
  const rounded = Math.max(0, Math.round(ms));
  return rounded <= MAX_ELAPSED_MS ? rounded : undefined;
}
