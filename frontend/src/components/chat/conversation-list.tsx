"use client";

import { Compass, SquarePen, Sun, Target, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { InlineConfirm } from "@/components/ui/inline-confirm";
import { ScrollArea } from "@/components/ui/scroll-area";
import type { Conversation } from "@/lib/types";
import { cn } from "@/lib/utils";

type Props = {
  conversations: Conversation[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
  onDelete: (id: string) => void;
  className?: string;
};

type Group = "today" | "week" | "earlier";

const DAY_MS = 24 * 60 * 60 * 1000;

/** Today, the past seven days, or before, by when it was last active (local time). */
export function groupOf(updatedAt: string, now = new Date()): Group {
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const at = new Date(updatedAt).getTime();
  if (at >= startOfToday) return "today";
  if (at >= startOfToday - 6 * DAY_MS) return "week";
  return "earlier";
}

/**
 * The learner's conversations, newest first under date headings (component-spec "对话页").
 * A sidebar column on desktop; the chat page puts the same list in a drawer on phones.
 */
export function ConversationList({
  conversations,
  activeId,
  onSelect,
  onNew,
  onDelete,
  className,
}: Props) {
  const t = useTranslations("chat");
  const groups: { key: Group; items: Conversation[] }[] = [];
  for (const c of conversations) {
    const key = groupOf(c.updated_at);
    const last = groups.at(-1);
    if (last?.key === key) last.items.push(c);
    else groups.push({ key, items: [c] });
  }

  return (
    <aside
      className={cn(
        "flex w-64 shrink-0 flex-col border-r bg-[color-mix(in_oklab,var(--sidebar)_60%,var(--background))]",
        className,
      )}
    >
      <div className="px-2.5 pt-3.5 pb-2">
        <Button variant="outline" className="w-full justify-start bg-card" onClick={onNew}>
          <SquarePen aria-hidden />
          {t("newChat")}
        </Button>
      </div>
      <ScrollArea className="min-h-0 flex-1">
        <nav aria-label={t("conversations")} className="flex flex-col px-2.5 pb-3">
          {groups.map(({ key, items }) => (
            <section key={key} aria-labelledby={`conversations-${key}`} className="mt-2.5">
              <h3
                id={`conversations-${key}`}
                className="px-2.5 pb-1 text-[11.5px] font-semibold text-muted-foreground"
              >
                {t(`groups.${key}`)}
              </h3>
              <ul className="flex flex-col gap-0.5">
                {items.map((c) => (
                  <ConversationRow
                    key={c.id}
                    conversation={c}
                    active={c.id === activeId}
                    onSelect={onSelect}
                    onDelete={onDelete}
                  />
                ))}
              </ul>
            </section>
          ))}
        </nav>
      </ScrollArea>
    </aside>
  );
}

function ConversationRow({
  conversation: c,
  active,
  onSelect,
  onDelete,
}: {
  conversation: Conversation;
  active: boolean;
  onSelect: (id: string) => void;
  onDelete: (id: string) => void;
}) {
  const t = useTranslations("chat");
  const icon = "mr-2 inline size-3.5 shrink-0 align-[-2px] text-muted-foreground";
  return (
    <li className="group relative">
      <button
        type="button"
        onClick={() => onSelect(c.id)}
        aria-current={active ? "page" : undefined}
        className={cn(
          "h-9 w-full truncate rounded-md px-2.5 pr-9 text-left text-[13.5px] transition-colors outline-none hover:bg-accent/60 focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-ring",
          active && "bg-accent font-semibold text-accent-foreground hover:bg-accent",
        )}
      >
        {c.focus_kc && <Target className={icon} aria-label={t("practice.badge")} />}
        {c.purpose === "planning" && <Compass className={icon} aria-label={t("planning.badge")} />}
        {c.purpose === "daily" && <Sun className={icon} aria-label={t("daily.badge")} />}
        {c.title || t("untitled")}
      </button>
      <InlineConfirm
        question={t("confirmDelete")}
        onConfirm={() => onDelete(c.id)}
        compact
        className="absolute inset-0 rounded-md bg-accent pr-1 pl-2.5"
      >
        {(ask) => (
          <button
            type="button"
            aria-label={t("delete")}
            onClick={ask}
            className="absolute top-1/2 right-1.5 flex size-6 -translate-y-1/2 items-center justify-center rounded-sm text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100 hover:bg-muted hover:text-destructive focus-visible:opacity-100 focus-visible:outline-2 focus-visible:outline-ring [@media(hover:none)]:opacity-100"
          >
            <Trash2 className="size-3.5" />
          </button>
        )}
      </InlineConfirm>
    </li>
  );
}
