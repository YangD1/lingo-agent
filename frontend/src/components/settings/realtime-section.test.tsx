import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import type { RealtimeLimits } from "@/lib/types";

import en from "../../../messages/en.json";
import { RealtimeSection } from "./realtime-section";

const api = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  api,
}));

const LIMITS: RealtimeLimits = { session_minutes: 15, daily_minutes: 30, used_minutes: 4.5, state: "ok" };

function show() {
  return render(
    <NextIntlClientProvider locale="en" messages={en} timeZone="UTC">
      <RealtimeSection />
    </NextIntlClientProvider>,
  );
}

beforeEach(() => {
  api.mockReset(); // in a block: a function returned from beforeEach runs as cleanup
});

describe("RealtimeSection", () => {
  it("stays hidden from learners who don't manage the workspace", async () => {
    api.mockRejectedValue(new ApiError(403, "forbidden", "no"));
    const { container } = show();
    await waitFor(() => expect(api).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it("saves new limits and says when calls are off", async () => {
    let stored = LIMITS;
    api.mockImplementation(async (_path: string, init?: { json?: Partial<RealtimeLimits> }) => {
      if (init?.json) {
        stored = { ...stored, ...init.json };
        stored = { ...stored, state: stored.session_minutes === 0 ? "off" : "ok" };
      }
      return stored;
    });
    show();

    expect(await screen.findByText("You have used 4.5 of 30 minutes today (UTC).")).toBeInTheDocument();
    const session = screen.getByLabelText("One call (minutes)");
    const save = screen.getByRole("button", { name: "Save" });
    expect(save).toBeDisabled(); // nothing changed yet

    await userEvent.clear(session);
    await userEvent.type(session, "61");
    expect(session).toHaveAttribute("aria-invalid", "true");
    expect(save).toBeDisabled();

    await userEvent.clear(session);
    await userEvent.type(session, "0");
    await userEvent.click(save);

    expect(api).toHaveBeenCalledWith("/tenant/realtime", {
      method: "PUT",
      json: { session_minutes: 0, daily_minutes: 30 },
    });
    expect(
      await screen.findByText("Realtime calls are off for everyone in this workspace."),
    ).toBeInTheDocument();
  });
});
