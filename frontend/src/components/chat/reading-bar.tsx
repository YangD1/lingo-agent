"use client";

import { Newspaper } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { useState } from "react";

import { Callout } from "@/components/ui/callout";
import { useWorkspaceOpener } from "@/components/workspace/opener";
import { cn } from "@/lib/utils";

const action = "shrink-0 text-[13px] font-medium text-primary underline-offset-2 hover:underline";

/** Says that a reading conversation is about an article, with the way back to it (Q43h)
 * and, on the chat page, the article opened in the workspace (ADR 0043 §3). */
export function ReadingBar({ articleId }: { articleId: number }) {
  const t = useTranslations("chat.reading");
  const workspace = useWorkspaceOpener();
  const [opening, setOpening] = useState(false);

  async function open() {
    if (!workspace) return;
    setOpening(true);
    try {
      await workspace.openFrom({ source: "article", id: articleId });
    } finally {
      setOpening(false);
    }
  }

  return (
    <Callout
      tone="neutral"
      icon={<Newspaper aria-hidden />}
      className="mx-auto mt-3 w-[calc(100%-1.5rem)] max-w-3xl"
      data-testid="reading-bar"
      action={
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          {workspace && (
            <button
              type="button"
              className={cn(action, "disabled:opacity-60")}
              disabled={opening}
              onClick={() => void open()}
            >
              {t("workspace")}
            </button>
          )}
          <Link href={`/reading/${articleId}`} className={action}>
            {t("back")}
          </Link>
        </div>
      }
    >
      {t("label")}
    </Callout>
  );
}
