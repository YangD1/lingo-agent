import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Placement } from "@/lib/placement";

import en from "../../../messages/en.json";
import { PlacementBanner } from "./placement-banner";

const api = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  api,
}));

const placement = (status: Placement["status"], retestDue = false): Placement => ({
  id: "p1",
  status,
  stage: "vocab",
  answered: 3,
  question: null,
  result: null,
  created_at: "2026-09-30T00:00:00Z",
  finished_at: status === "done" ? "2026-07-01T00:00:00Z" : null,
  retest_due: retestDue,
});

function show() {
  return render(
    <NextIntlClientProvider locale="en" messages={en}>
      <PlacementBanner />
    </NextIntlClientProvider>,
  );
}

beforeEach(() => api.mockReset());
afterEach(() => window.localStorage.clear());

describe("PlacementBanner", () => {
  it("invites a learner who never took the test, until closed", async () => {
    api.mockResolvedValue(null);
    const { unmount } = show();
    expect(await screen.findByRole("link", { name: "Take the test" })).toHaveAttribute(
      "href",
      "/placement",
    );

    await userEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(screen.queryByTestId("placement-banner")).not.toBeInTheDocument();
    unmount();
    show();
    await vi.waitFor(() => expect(api).toHaveBeenCalledTimes(2));
    expect(screen.queryByTestId("placement-banner")).not.toBeInTheDocument();
  });

  it("still reminds of a test left halfway after the invitation was closed", async () => {
    window.localStorage.setItem("lingo.placementBannerClosed", "start");
    api.mockResolvedValue(placement("in_progress"));
    show();
    expect(await screen.findByRole("link", { name: "Continue" })).toBeInTheDocument();
  });

  it("says nothing once a test is done", async () => {
    api.mockResolvedValue(placement("done"));
    show();
    await vi.waitFor(() => expect(api).toHaveBeenCalled());
    expect(screen.queryByTestId("placement-banner")).not.toBeInTheDocument();
  });

  it("suggests a retest once the last test is over 60 days old, until closed", async () => {
    window.localStorage.setItem("lingo.placementBannerClosed", "start");
    api.mockResolvedValue(placement("done", true));
    const first = show();
    expect(await screen.findByRole("link", { name: "Retake" })).toHaveAttribute(
      "href",
      "/placement",
    );
    await userEvent.click(screen.getByRole("button", { name: "Close" }));
    first.unmount();

    const second = show();
    await vi.waitFor(() => expect(api).toHaveBeenCalledTimes(2));
    expect(screen.queryByTestId("placement-banner")).not.toBeInTheDocument();

    // A later test's retest reminder is not silenced by closing this one.
    second.unmount();
    api.mockResolvedValue({ ...placement("done", true), finished_at: "2026-12-01T00:00:00Z" });
    show();
    expect(await screen.findByRole("link", { name: "Retake" })).toBeInTheDocument();
  });
});
