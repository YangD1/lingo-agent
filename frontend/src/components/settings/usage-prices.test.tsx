import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Prices } from "@/lib/types";

import en from "../../../messages/en.json";
import { UsagePrices } from "./usage-prices";

const api = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  api,
}));

const saved: Prices = {
  currency: "USD",
  prices: [
    {
      connection: "old",
      model: "m1",
      input_per_mtok: 1,
      output_per_mtok: null,
      per_kchar: null,
      per_minute: null,
    },
  ],
};

function show(onSaved = vi.fn()) {
  render(
    <NextIntlClientProvider locale="en" messages={en}>
      <UsagePrices models={[{ connection: "openai", model: "gpt-5-mini" }]} onSaved={onSaved} />
    </NextIntlClientProvider>,
  );
  return onSaved;
}

beforeEach(() => api.mockReset());

describe("UsagePrices", () => {
  it("lists used and already priced models, and saves the whole list", async () => {
    api.mockImplementation((_path: string, init?: { method?: string; json?: Prices }) =>
      Promise.resolve(init?.method === "PUT" ? init.json : saved),
    );
    const onSaved = show();

    await userEvent.click(screen.getByText("Prices"));
    expect(await screen.findByLabelText("old:m1 · Input / 1M tokens")).toHaveValue(1);
    await userEvent.type(screen.getByLabelText("openai:gpt-5-mini · Output / 1M tokens"), "8");
    await userEvent.click(screen.getByRole("button", { name: "Save prices" }));

    expect(api).toHaveBeenLastCalledWith("/tenant/prices", {
      method: "PUT",
      json: {
        currency: "USD",
        prices: [
          { ...saved.prices[0] },
          {
            connection: "openai",
            model: "gpt-5-mini",
            input_per_mtok: null,
            output_per_mtok: 8,
            per_kchar: null,
            per_minute: null,
          },
        ],
      },
    });
    expect(onSaved).toHaveBeenCalled();
  });

  it("won't save a negative price", async () => {
    api.mockResolvedValue({ currency: "CNY", prices: [] } satisfies Prices);
    show();

    await userEvent.click(screen.getByText("Prices"));
    await userEvent.type(await screen.findByLabelText("openai:gpt-5-mini · Per minute"), "-1");

    expect(screen.getByRole("button", { name: "Save prices" })).toBeDisabled();
  });
});
