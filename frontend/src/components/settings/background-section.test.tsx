import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import type { MyBackground, TenantBackground } from "@/lib/types";

import en from "../../../messages/en.json";
import { BackgroundSection } from "./background-section";

const api = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  api,
}));

function mine(enabled: boolean, budget: MyBackground["budget"] = "ok"): MyBackground {
  return {
    features: [
      { key: "practice_prefetch", enabled, default: true, usage_feature: "practice_set" },
    ],
    budget,
  };
}

const TENANT: TenantBackground = {
  daily_tokens: 100_000,
  used_today: 1234,
  budget: "ok",
  scheduler_running: true,
  jobs: [
    {
      job: "fetch_feeds",
      next_run_at: "2026-10-07T14:00:00Z",
      last_started_at: "2026-10-07T12:00:00Z",
      last_finished_at: "2026-10-07T12:00:05Z",
      last_success_at: null,
      last_status: "skipped",
      last_skip_reason: "budget_exhausted",
      last_error: null,
    },
  ],
};

function show() {
  return render(
    <NextIntlClientProvider locale="en" messages={en} timeZone="UTC">
      <BackgroundSection />
    </NextIntlClientProvider>,
  );
}

beforeEach(() => api.mockReset());

describe("BackgroundSection", () => {
  it("lets a learner switch a background feature off, without the tenant budget", async () => {
    let enabled = true;
    api.mockImplementation(async (path: string, init?: { json?: { enabled: boolean } }) => {
      if (path === "/tenant/background") throw new ApiError(403, "forbidden", "no");
      if (init?.json) enabled = init.json.enabled;
      return mine(enabled);
    });
    show();

    const toggle = await screen.findByRole("switch", { name: "Prepare the next practice set" });
    expect(toggle).toBeChecked();
    await userEvent.click(toggle);

    expect(api).toHaveBeenCalledWith("/me/background/practice_prefetch", {
      method: "PUT",
      json: { enabled: false },
    });
    await waitFor(() => expect(toggle).not.toBeChecked());
    // Not a manager: no budget, no error for the 403.
    expect(screen.queryByText("Daily background budget")).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("tells the learner when today's budget is used up", async () => {
    api.mockImplementation(async (path: string) => {
      if (path === "/tenant/background") throw new ApiError(403, "forbidden", "no");
      return mine(true, "exhausted");
    });
    show();
    expect(
      await screen.findByText(/Today's background budget is used up; it resets tomorrow/),
    ).toBeInTheDocument();
  });

  it("shows managers today's use and jobs, and saves a new limit", async () => {
    let tenant = TENANT;
    api.mockImplementation(async (path: string, init?: { json?: { daily_tokens: number } }) => {
      if (path === "/me/background") return mine(true, tenant.budget);
      if (init?.json) tenant = { ...tenant, daily_tokens: init.json.daily_tokens, budget: "off" };
      return tenant;
    });
    show();

    expect(await screen.findByText("Used today: 1,234 / 100,000 tokens")).toBeInTheDocument();
    expect(screen.getByText("fetch_feeds")).toBeInTheDocument();
    expect(screen.getByText(/Last: skipped/)).toBeInTheDocument();
    expect(screen.getByText("Today's background budget was used up.")).toBeInTheDocument();

    const input = screen.getByLabelText("Daily limit (tokens)");
    const save = screen.getByRole("button", { name: "Save" });
    expect(save).toBeDisabled(); // unchanged
    await userEvent.clear(input);
    await userEvent.type(input, "0");
    await userEvent.click(save);

    expect(api).toHaveBeenCalledWith("/tenant/background", {
      method: "PUT",
      json: { daily_tokens: 0 },
    });
    expect(
      await screen.findByText(/An admin switched off all background model calls/),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Daily limit (tokens)")).toHaveValue(0);
  });
});
