"use client";

import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import { type FollowUp, splitReply } from "@/lib/follow-ups";

import { Markdown } from "./markdown";

/**
 * A tutor reply with its follow-ups (ADR 0064 §7): the reply's own text, then each
 * follow-up under a small heading, with how it is going or how it ended.
 */
export function ReplyParts({
  content,
  followUps,
}: {
  content: string;
  followUps: readonly FollowUp[] | undefined;
}) {
  return splitReply(content, followUps).map((part) =>
    part.followUp ? (
      <FollowUpPart key={part.followUp.index} followUp={part.followUp} text={part.text} />
    ) : (
      part.text && (
        <Markdown key={0} words>
          {part.text}
        </Markdown>
      )
    ),
  );
}

function FollowUpPart({ followUp, text }: { followUp: FollowUp; text: string }) {
  const t = useTranslations("chat.followUp");
  return (
    <section data-slot="follow-up" className="mt-3 border-t border-border/60 pt-2">
      <h3 className="text-xs font-medium tracking-wide text-muted-foreground">{t("heading")}</h3>
      {text && <Markdown words>{text}</Markdown>}
      {followUp.state === "writing" ? (
        <Elapsed since={followUp.startedAt} />
      ) : (
        followUp.outcome &&
        followUp.outcome !== "done" && (
          <p className="mt-1 text-xs text-muted-foreground">{t(followUp.outcome)}</p>
        )
      )}
    </section>
  );
}

/** "Still thinking it through… N s", counting from `since`. */
function Elapsed({ since }: { since: number | undefined }) {
  const t = useTranslations("chat.followUp");
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);
  const seconds = Math.max(0, Math.floor((now - (since ?? now)) / 1000));
  return (
    <p role="status" className="mt-1 text-xs text-muted-foreground">
      {t("writing", { seconds })}
    </p>
  );
}
