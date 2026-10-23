import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import type { DeepenSettings } from "@/lib/types";

import en from "../../../messages/en.json";
import { DeepenSection } from "./deepen-section";

const api = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  api,
}));

const DEFAULTS: DeepenSettings = {
  enabled: true,
  max_segments: 1,
  first_chunk_seconds: 15,
  total_seconds: 60,
  max_tokens: 1500,
};

function show() {
  return render(
    <NextIntlClientProvider locale="en" messages={en} timeZone="UTC">
      <DeepenSection />
    </NextIntlClientProvider>,
  );
}

beforeEach(() => {
  api.mockReset(); // in a block: a function returned from beforeEach runs as cleanup
});

describe("DeepenSection", () => {
  it("stays hidden from learners who don't manage the workspace", async () => {
    api.mockRejectedValue(new ApiError(403, "forbidden", "no"));
    const { container } = show();
    await waitFor(() => expect(api).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it("refuses values out of bounds and saves the limits", async () => {
    let stored = DEFAULTS;
    api.mockImplementation(async (_path: string, init?: { json?: DeepenSettings }) => {
      if (init?.json) stored = init.json;
      return stored;
    });
    show();

    const segments = await screen.findByLabelText("Follow-ups per reply (1–3)");
    const total = screen.getByLabelText("Longest follow-up (10–300 s)");
    const save = screen.getByRole("button", { name: "Save" });
    expect(segments).toHaveValue(1);
    expect(save).toBeDisabled(); // nothing changed yet

    await userEvent.clear(segments);
    await userEvent.type(segments, "4");
    expect(segments).toHaveAttribute("aria-invalid", "true");
    expect(save).toBeDisabled();

    await userEvent.clear(segments);
    await userEvent.type(segments, "2");
    await userEvent.clear(total);
    await userEvent.type(total, "120");
    await userEvent.click(save);

    expect(api).toHaveBeenCalledWith("/tenant/deepen", {
      method: "PUT",
      json: { ...DEFAULTS, max_segments: 2, total_seconds: 120 },
    });
    // Saved: the form is reset to what is stored, so there is nothing to save again.
    await waitFor(() => expect(screen.getByRole("button", { name: "Save" })).toBeDisabled());
    expect(screen.getByLabelText("Follow-ups per reply (1–3)")).toHaveValue(2);
  });

  it("turning follow-ups off greys out the limits", async () => {
    api.mockResolvedValue(DEFAULTS);
    show();

    const toggle = await screen.findByRole("switch", { name: "Allow follow-ups" });
    await userEvent.click(toggle);
    expect(screen.getByLabelText("Tokens per follow-up (256–8000)")).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(api).toHaveBeenLastCalledWith("/tenant/deepen", {
      method: "PUT",
      json: { ...DEFAULTS, enabled: false },
    });
  });
});
