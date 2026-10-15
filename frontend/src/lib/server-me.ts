import "server-only";

import { redirect } from "next/navigation";
import { cache } from "react";

import { ApiError } from "./api";
import { serverApi } from "./server-api";
import type { Me } from "./types";

/**
 * The signed-in learner, checked with the backend; an expired session leaves the app.
 * Once per request: a layout and its page may both ask.
 */
export const getMe = cache(async (): Promise<Me> => {
  try {
    return await serverApi<Me>("/auth/me");
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) redirect("/session-expired");
    throw error;
  }
});
