import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Usage, UsageRow } from "@/lib/types";

import en from "../../../messages/en.json";
import { UsageDetails } from "./usage-details";

const api = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  api,
}));

const row = (overrides: Partial<UsageRow>): UsageRow => ({
  day: "2026-10-12",
  connection: "openai",
  model: "gpt-5-mini",
  calls: 1,
  input_tokens: 10,
  output_tokens: 5,
  characters: 0,
  errors: 0,
  fallbacks: 0,
  avg_latency_ms: 100,
  member: null,
  ...overrides,
});

function show() {
  return render(
    <NextIntlClientProvider locale="en" messages={en}>
      <UsageDetails days={7} reload={0} />
    </NextIntlClientProvider>,
  );
}

beforeEach(() => api.mockReset());

describe("UsageDetails", () => {
  it("shows the account's own use, without a picker when nobody else uses its models", async () => {
    api.mockResolvedValue({ days: 7, rows: [row({})] } satisfies Usage);
    show();

    expect(await screen.findByRole("table", { name: "Details (per day and model)" })).toHaveTextContent("openai:gpt-5-mini");
    expect(screen.queryByRole("combobox", { name: "Whose use" })).not.toBeInTheDocument();
  });

  it("shows each member's use on this account's connections apart (ADR 0031 §8)", async () => {
    api.mockResolvedValue({
      days: 7,
      rows: [row({ input_tokens: 10 }), row({ member: "Alex", input_tokens: 700 })],
    } satisfies Usage);
    show();

    const table = await screen.findByRole("table", { name: "Details (per day and model)" });
    expect(within(table).getByRole("row", { name: /Total/ })).toHaveTextContent("10");
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Whose use" }), "Alex");

    expect(within(table).getByRole("row", { name: /Total/ })).toHaveTextContent("700");
    expect(within(table).getAllByRole("row")).toHaveLength(3); // head, Alex's row, total
  });
});
