import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { MyUsage } from "@/lib/types";

import en from "../../../messages/en.json";
import { MyUsageCard } from "./my-usage-card";

const api = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  api,
}));

type Use = MyUsage["capabilities"][number];
const use = (capability: Use["capability"], unit: Use["unit"], month: number, quota: Use["quota"] = null): Use => ({
  capability,
  unit,
  month,
  quota,
});

function show() {
  render(
    <NextIntlClientProvider locale="en" messages={en}>
      <MyUsageCard />
    </NextIntlClientProvider>,
  );
}

beforeEach(() => api.mockReset());

describe("MyUsageCard", () => {
  it("shows only what was used, without quotas for an account of its own", async () => {
    api.mockResolvedValue({
      month_start: "2026-10-01",
      sponsor_name: null,
      capabilities: [use("text", "tokens", 12345), use("tts", "characters", 0), use("asr", "minutes", 1.5)],
    } satisfies MyUsage);
    show();

    expect(await screen.findByTestId("usage-text")).toHaveTextContent("Chat and text12,345 tokens");
    expect(screen.getByTestId("usage-asr")).toHaveTextContent("1.5 minutes");
    expect(screen.queryByTestId("usage-tts")).not.toBeInTheDocument();
    expect(screen.queryByText(/left/)).not.toBeInTheDocument();
  });

  it("shows a member what's left of the main account's quotas", async () => {
    const quota = { daily: 1000, monthly: 5000, day: 400, month: 400 };
    api.mockResolvedValue({
      month_start: "2026-10-01",
      sponsor_name: "Team",
      capabilities: [
        use("text", "tokens", 450, { ...quota, left: 600 }),
        use("tts", "characters", 0, { daily: null, monthly: null, day: 0, month: 0, left: null }),
        use("realtime", "minutes", 0, { daily: 0, monthly: null, day: 0, month: 0, left: 0 }),
      ],
    } satisfies MyUsage);
    show();

    expect(await screen.findByTestId("usage-text")).toHaveTextContent("600 tokens left");
    expect(screen.getByTestId("usage-tts")).toHaveTextContent("No cap");
    expect(screen.getByTestId("usage-realtime")).toHaveTextContent("Off");
    expect(screen.getByText(/quota Team gives you/)).toBeInTheDocument();
  });

  it("says so before any use", async () => {
    api.mockResolvedValue({ month_start: "2026-10-01", sponsor_name: null, capabilities: [use("text", "tokens", 0)] });
    show();

    expect(await screen.findByText("No AI use yet this month.")).toBeInTheDocument();
  });
});
