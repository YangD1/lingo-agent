import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { resetEstimatesCache, type UsageEstimates } from "@/lib/ai-usage";
import type { Prices, UsageDashboard, UsageTally } from "@/lib/types";

import en from "../../../messages/en.json";
import { UsageSection } from "./usage-section";

const api = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  api,
}));
// Recharts needs a laid-out DOM; the chart gets its own check in E2E.
vi.mock("./usage-chart", () => ({
  UsageChart: ({ metric }: { metric: string }) => <div data-testid="usage-chart">{metric}</div>,
}));

const tally = (overrides: Partial<UsageTally> = {}): UsageTally => ({
  calls: 4,
  input_tokens: 1000,
  output_tokens: 200,
  characters: 0,
  audio_minutes: 0,
  errors: 0,
  fallbacks: 0,
  cost: null,
  cost_partial: false,
  ...overrides,
});

const board = (overrides: Partial<UsageDashboard> = {}): UsageDashboard => ({
  days: 7,
  total: tally({ calls: 10, errors: 1 }),
  series: [{ day: "2026-10-13", ...tally() }],
  tasks: [
    { task: "chat", background: false, ...tally({ calls: 6 }) },
    { task: "reflect", background: true, ...tally({ calls: 4 }) },
  ],
  models: [{ connection: "openai", model: "gpt-5-mini", ...tally({ calls: 10 }) }],
  members: [{ member: null, ...tally({ calls: 10 }) }],
  priced: false,
  currency: "USD",
  ...overrides,
});

const estimates: UsageEstimates = {
  window: 20,
  features: [
    { feature: "chat_message", calls: [{ task: "reflect" } as UsageEstimates["features"][0]["calls"][0]] },
    { feature: "speaking_turn", calls: [{ task: "reflect" } as UsageEstimates["features"][0]["calls"][0]] },
  ],
};

function respond(dashboard: UsageDashboard, prices?: Prices) {
  api.mockImplementation((path: string) => {
    if (path.startsWith("/tenant/usage/dashboard")) return Promise.resolve(dashboard);
    if (path === "/usage/estimates") return Promise.resolve(estimates);
    if (path === "/tenant/prices") return Promise.resolve(prices ?? { currency: "CNY", prices: [] });
    return Promise.reject(new Error(path));
  });
}

function show() {
  return render(
    <NextIntlClientProvider locale="en" messages={en}>
      <UsageSection />
    </NextIntlClientProvider>,
  );
}

beforeEach(() => {
  api.mockReset();
  resetEstimatesCache();
});

describe("UsageSection", () => {
  it("shows totals, the daily chart and what each use cost in calls, without costs unpriced", async () => {
    respond(board());
    show();

    const totals = await screen.findByLabelText("Totals");
    expect(totals).toHaveTextContent("Calls10");
    expect(totals).toHaveTextContent("Error rate10%");
    expect(totals).not.toHaveTextContent("Estimated cost");
    expect(screen.getByTestId("usage-chart")).toHaveTextContent("calls");
    expect(screen.queryByRole("radio", { name: "Cost" })).not.toBeInTheDocument();

    const uses = screen.getByRole("table", { name: "By use" });
    expect(within(uses).getByRole("row", { name: /^Reply/ })).toBeInTheDocument();
    const reflect = within(uses).getByRole("cell", { name: /Background/ });
    expect(reflect).toHaveAttribute("title", "Used by: Tutor chat, Speaking practice");
    // Only one account: no member grouping.
    expect(screen.queryByRole("radio", { name: "By member" })).not.toBeInTheDocument();
  });

  it("shows costs once priced, marking partial ones", async () => {
    respond(
      board({
        priced: true,
        total: tally({ calls: 10, cost: 1.5, cost_partial: true }),
        models: [
          { connection: "openai", model: "gpt-5-mini", ...tally({ cost: 1.5 }) },
          { connection: "deepseek", model: "deepseek-chat", ...tally() },
        ],
      }),
    );
    show();

    expect(await screen.findByLabelText("Totals")).toHaveTextContent("$1.50");
    expect(screen.getByLabelText("Totals")).toHaveTextContent("Partial");
    await userEvent.click(screen.getByRole("radio", { name: "Cost" }));
    expect(screen.getByTestId("usage-chart")).toHaveTextContent("cost");

    await userEvent.click(screen.getByRole("radio", { name: "By model" }));
    const models = screen.getByRole("table", { name: "By model" });
    expect(within(models).getByRole("row", { name: /openai:gpt-5-mini/ })).toHaveTextContent("$1.50");
    expect(within(models).getByRole("row", { name: /deepseek/ })).toHaveTextContent("—");
  });

  it("groups by member when members use this account's connections (ADR 0031 §8)", async () => {
    respond(
      board({
        members: [
          { member: null, ...tally({ calls: 6 }) },
          { member: "Alex", ...tally({ calls: 4 }) },
        ],
      }),
    );
    show();

    await userEvent.click(await screen.findByRole("radio", { name: "By member" }));
    const rows = within(screen.getByRole("table", { name: "By member" })).getAllByRole("row").slice(1);
    expect(rows.map((r) => r.firstElementChild?.textContent)).toEqual(["Mine", "Alex"]);
  });

  it("says so when nothing was called", async () => {
    respond(board({ total: tally({ calls: 0 }), tasks: [], models: [], members: [] }));
    show();

    expect(await screen.findByText("No model calls in this period.")).toBeInTheDocument();
  });
});
