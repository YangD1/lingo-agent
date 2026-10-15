"use client";

import { createContext, useContext } from "react";

/**
 * Opens a workspace document beside the chat. Only the chat page provides it: elsewhere
 * (the dashboard's dialog, the desk pet's window) there is no room for the workspace.
 */
export const WorkspaceOpener = createContext<((docId: string) => void) | null>(null);

export const useWorkspaceOpener = () => useContext(WorkspaceOpener);
