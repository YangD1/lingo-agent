import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { PlacementReminder } from "@/lib/placement";

import en from "../../../messages/en.json";
import { PlacementBanner } from "./placement-banner";

const api = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  api,
}));

const reminder = (over: Partial<PlacementReminder>): PlacementReminder => ({
  reason: "never",
  key: "never",
  days_since: null,
  level: null,
  learned: null,
  total: null,
  snoozed: false,
  ...over,
});

function show() {
  return render(
    <NextIntlClientProvider locale="en" messages={en}>
      <PlacementBanner />
    </NextIntlClientProvider>,
  );
}

beforeEach(() => api.mockReset());

describe("PlacementBanner", () => {
  it("invites a learner who never took the test; Not now goes to the server", async () => {
    api.mockResolvedValue(reminder({}));
    show();
    expect(await screen.findByRole("link", { name: "Take the test" })).toHaveAttribute(
      "href",
      "/placement",
    );

    api.mockResolvedValue(undefined);
    await userEvent.click(screen.getByRole("button", { name: "Not now" }));

    expect(screen.queryByTestId("placement-banner")).not.toBeInTheDocument();
    expect(api).toHaveBeenLastCalledWith("/placement/reminder/dismiss", {
      method: "POST",
      json: { key: "never" },
    });
  });

  it("says why a retest is due", async () => {
    api.mockResolvedValue(
      reminder({
        reason: "progress",
        key: "progress:p1",
        days_since: 20,
        level: "B1",
        learned: 24,
        total: 33,
      }),
    );
    show();
    expect(
      await screen.findByText(
        "You've learned 24 of the 33 B1 grammar points. Retake the test to see if you've moved up a level.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Retake" })).toHaveAttribute("href", "/placement");
  });

  it("reminds of a test left halfway, and of an old one", async () => {
    api.mockResolvedValue(reminder({ reason: "resume", key: "resume:p2" }));
    const first = show();
    expect(await screen.findByRole("link", { name: "Continue" })).toBeInTheDocument();
    first.unmount();

    api.mockResolvedValue(reminder({ reason: "age", key: "age:p1", days_since: 75 }));
    show();
    expect(
      await screen.findByText("Your last placement test was 75 days ago. Retake it to see your progress."),
    ).toBeInTheDocument();
  });

  it("says nothing when there is nothing to remind of, or after Not now", async () => {
    api.mockResolvedValue(null);
    const first = show();
    await vi.waitFor(() => expect(api).toHaveBeenCalledTimes(1));
    expect(screen.queryByTestId("placement-banner")).not.toBeInTheDocument();
    first.unmount();

    api.mockResolvedValue(reminder({ snoozed: true }));
    show();
    await vi.waitFor(() => expect(api).toHaveBeenCalledTimes(2));
    expect(screen.queryByTestId("placement-banner")).not.toBeInTheDocument();
  });
});
