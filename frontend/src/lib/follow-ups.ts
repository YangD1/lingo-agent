/**
 * Follow-ups under a tutor reply (ADR 0064 §7): the reply's content holds them all, one
 * after another, each from its offset; the page shows each under its own heading.
 */

/** How a follow-up ended: done, at the tenant's time or length limit, the model failed,
 * nothing came in time (no_start), or the learner stopped it (stopped, this page only). */
export type FollowUpOutcome = "done" | "timeout" | "length" | "failed" | "no_start" | "stopped";

export type FollowUp = {
  index: number;
  /** Where its text starts in the reply's content; null while none has come yet. */
  offset: number | null;
  /** writing: still streaming; ended: see `outcome`. */
  state: "writing" | "ended";
  outcome?: FollowUpOutcome;
  /** When it started here (Date.now()), for the time shown while it is written. */
  startedAt?: number;
};

/** What the history API gives for each follow-up joined into a reply. */
export type FollowUpOut = { index: number; outcome: string; offset: number };

/** The separator the backend streams (and joins history with) between parts of a reply. */
export const PART_SEPARATOR = "\n\n";

export const fromHistory = (saved: readonly FollowUpOut[] | undefined): FollowUp[] | undefined =>
  saved?.length
    ? saved.map((f) => ({
        index: f.index,
        offset: f.offset,
        state: "ended",
        outcome: f.outcome as FollowUpOutcome,
      }))
    : undefined;

export type ReplyPart = { followUp: FollowUp | null; text: string };

/** The reply's own text, then each follow-up's; follow-ups with no text yet come empty. */
export function splitReply(content: string, followUps: readonly FollowUp[] | undefined): ReplyPart[] {
  if (!followUps?.length) return [{ followUp: null, text: content }];
  const starts = followUps.map((f) => f.offset ?? content.length);
  const parts: ReplyPart[] = [{ followUp: null, text: content.slice(0, starts[0]).trimEnd() }];
  followUps.forEach((f, i) => {
    const text = f.offset === null ? "" : content.slice(f.offset, starts[i + 1] ?? content.length);
    parts.push({ followUp: f, text: text.trimEnd() });
  });
  return parts;
}

/** A follow-up starts: it has no text until its first token. */
export function started(followUps: readonly FollowUp[] | undefined, index: number, now: number): FollowUp[] {
  return [...(followUps ?? []), { index, offset: null, state: "writing", startedAt: now }];
}

/**
 * A token arrives with `content` the text so far: the first one of a follow-up (the
 * separator before it aside) marks where its text starts.
 */
export function withToken(followUps: FollowUp[] | undefined, content: string, token: string): FollowUp[] | undefined {
  const last = followUps?.at(-1);
  if (!followUps || !last || last.state !== "writing" || last.offset !== null) return followUps;
  if (token === PART_SEPARATOR) return followUps;
  return [...followUps.slice(0, -1), { ...last, offset: content.length }];
}

export function ended(
  followUps: readonly FollowUp[] | undefined,
  index: number,
  outcome: FollowUpOutcome,
): FollowUp[] | undefined {
  return followUps?.map((f) => (f.index === index ? { ...f, state: "ended", outcome } : f));
}

/** The follow-up being written, if any: the learner may send while it is (ADR 0064 §6). */
export const writing = (followUps: readonly FollowUp[] | undefined): FollowUp | undefined =>
  followUps?.find((f) => f.state === "writing");

/**
 * The learner stopped the reply while a follow-up was being written: the backend keeps
 * the reply but not that follow-up (ADR 0064 §6). Its text goes, a "stopped" line stays.
 */
export function stoppedWhileWriting(
  content: string,
  followUps: readonly FollowUp[],
): { content: string; followUps: FollowUp[] } {
  const cut = followUps.find((f) => f.state === "writing");
  if (!cut) return { content, followUps: [...followUps] };
  const end = cut.offset ?? content.length;
  return {
    content: content.slice(0, end).replace(/\s+$/, ""),
    followUps: followUps.map((f) =>
      f === cut ? { ...f, offset: null, state: "ended", outcome: "stopped" } : f,
    ),
  };
}
