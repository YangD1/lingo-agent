"use client";

import { Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import type { Conversation } from "@/lib/types";
import { cn } from "@/lib/utils";

type Props = {
  conversations: Conversation[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
  onDelete: (id: string) => void;
};

export function ConversationList({ conversations, activeId, onSelect, onNew, onDelete }: Props) {
  const t = useTranslations("chat");
  return (
    <aside className="flex w-64 shrink-0 flex-col border-r">
      <div className="p-3">
        <Button variant="outline" className="w-full" onClick={onNew}>
          {t("newChat")}
        </Button>
      </div>
      <ScrollArea className="min-h-0 flex-1">
        <ul className="flex flex-col gap-1 px-2 pb-2" aria-label={t("conversations")}>
          {conversations.map((c) => (
            <li key={c.id} className="group relative">
              <button
                type="button"
                onClick={() => onSelect(c.id)}
                aria-current={c.id === activeId ? "page" : undefined}
                className={cn(
                  "w-full truncate rounded-md px-3 py-2 pr-9 text-left text-sm hover:bg-muted",
                  c.id === activeId && "bg-muted font-medium",
                )}
              >
                {c.title || t("untitled")}
              </button>
              <button
                type="button"
                aria-label={t("delete")}
                onClick={() => {
                  if (window.confirm(t("confirmDelete"))) onDelete(c.id);
                }}
                className="absolute top-1/2 right-2 -translate-y-1/2 rounded p-1 text-muted-foreground opacity-0 group-hover:opacity-100 hover:text-destructive focus:opacity-100"
              >
                <Trash2 className="size-4" />
              </button>
            </li>
          ))}
        </ul>
      </ScrollArea>
    </aside>
  );
}
