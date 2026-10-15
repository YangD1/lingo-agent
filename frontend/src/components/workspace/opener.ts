"use client";

import { createContext, useContext } from "react";

import type { DocSource } from "@/lib/workspace";

export type WorkspaceOpener = {
  /** Open a document of this conversation beside the chat. */
  open: (docId: string) => void;
  /** Open the document made from an article or a submitted text, making it the first time. */
  openFrom: (from: DocSource) => Promise<void>;
};

/**
 * Opens workspace documents beside the chat. Only the chat page provides it: elsewhere
 * (the dashboard's dialog, the desk pet's window) there is no room for the workspace.
 */
export const WorkspaceOpenerContext = createContext<WorkspaceOpener | null>(null);

export const useWorkspaceOpener = () => useContext(WorkspaceOpenerContext);
