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

const placement = (status: Placement["status"]): Placement => ({
  id: "p1",
  status,
  stage: "vocab",
  answered: 3,
  question: null,
  result: null,
  created_at: "2026-09-30T00:00:00Z",
  finished_at: null,
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
});
