"use client";

import { useRouter } from "next/navigation";
import { createContext, useContext } from "react";

import { courseChatHref } from "@/lib/course";
import type { Conversation } from "@/lib/types";

/**
 * Switches the chat page to another conversation. Navigating within /chat keeps the page
 * and its state, so a lesson card or the lesson bar's next lesson would change only the
 * address bar: on the chat page they switch through this instead (ADR 0054 §1).
 */
export const ConversationOpenerContext = createContext<((c: Conversation) => void) | null>(null);

/** Opens a conversation: in place on the chat page, by navigating elsewhere. */
export function useOpenConversation(): (c: Conversation) => void {
  const open = useContext(ConversationOpenerContext);
  const router = useRouter();
  return open ?? ((c) => router.push(courseChatHref(c.id)));
}
