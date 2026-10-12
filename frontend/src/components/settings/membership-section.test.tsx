import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import type { InvitePreview, Membership, Quotas } from "@/lib/org";

import en from "../../../messages/en.json";
import { JoinPanel, MembershipSection } from "./membership-section";

const api = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  api,
}));

const QUOTAS: Quotas = {
  text: { daily: 50_000, monthly: null },
  tts: { daily: 10_000, monthly: null },
  asr: { daily: 0, monthly: 0 },
  pronunciation: { daily: 0, monthly: 0 },
  realtime: { daily: 0, monthly: 0 },
};
const nothing = { day: 0, month: 0 };
const MEMBERSHIP: Membership = {
  sponsor_name: "Riverside School",
  joined_at: "2026-10-12T08:00:00Z",
  quotas: QUOTAS,
  usage: {
    text: { day: 1200, month: 3400 },
    tts: nothing,
    asr: nothing,
    pronunciation: nothing,
    realtime: nothing,
  },
};
const PREVIEW: InvitePreview = {
  sponsor_name: "Riverside School",
  quotas: QUOTAS,
  expires_at: "2026-10-19T08:00:00Z",
};

function show(ui: React.ReactNode) {
  return render(
    <NextIntlClientProvider locale="en" messages={en} timeZone="UTC">
      {ui}
    </NextIntlClientProvider>,
  );
}

beforeEach(() => api.mockReset());

describe("MembershipSection", () => {
  it("shows whose models a member uses, what's left, and leaves after asking", async () => {
    let membership: Membership | null = MEMBERSHIP;
    api.mockImplementation(async (path: string, init?: { method?: string }) => {
      if (init?.method === "DELETE") membership = null;
      return path === "/org/membership" && !init ? membership : undefined;
    });
    show(<MembershipSection />);

    expect(await screen.findByText("Using models from Riverside School since Oct 12, 2026.")).toBeInTheDocument();
    expect(screen.getByRole("row", { name: /Chat and text/ })).toHaveTextContent("1,200 / 50,000");
    await userEvent.click(screen.getByRole("button", { name: "Leave" }));
    await userEvent.click(screen.getByRole("button", { name: "Leave" }));

    expect(api).toHaveBeenCalledWith("/org/membership", { method: "DELETE" });
    // Back to joining with a code.
    expect(await screen.findByLabelText("Invite code")).toBeInTheDocument();
  });

  it("joins with a code: first what's shared, then agreeing", async () => {
    let membership: Membership | null = null;
    api.mockImplementation(async (path: string) => {
      if (path === "/org/join/preview") return PREVIEW;
      if (path === "/org/join") membership = MEMBERSHIP;
      if (path === "/org/membership") return membership;
      return undefined;
    });
    show(<MembershipSection />);

    await userEvent.type(await screen.findByLabelText("Invite code"), "  CODE-1 ");
    await userEvent.click(screen.getByRole("button", { name: "Check" }));

    expect(api).toHaveBeenCalledWith("/org/join/preview", { method: "POST", json: { code: "CODE-1" } });
    expect(await screen.findByText("Riverside School offers you these quotas:")).toBeInTheDocument();
    const offered = screen.getByRole("table", { name: "Quotas offered" });
    expect(within(offered).getByRole("row", { name: /Speech to text/ })).toHaveTextContent("OffOff");
    expect(screen.getByText(/not your conversations, memories or learning records/)).toBeInTheDocument();
    expect(api).not.toHaveBeenCalledWith("/org/join", expect.anything());

    await userEvent.click(screen.getByRole("button", { name: "Join Riverside School" }));

    expect(api).toHaveBeenCalledWith("/org/join", { method: "POST", json: { code: "CODE-1" } });
    expect(await screen.findByText(/Using models from Riverside School/)).toBeInTheDocument();
  });
});

describe("JoinPanel", () => {
  it("looks up the code from an invite link right away", async () => {
    api.mockResolvedValue(PREVIEW);
    show(<JoinPanel code="LINK-CODE" onJoined={() => {}} />);

    expect(await screen.findByRole("button", { name: "Join Riverside School" })).toBeEnabled();
    expect(api).toHaveBeenCalledWith("/org/join/preview", { method: "POST", json: { code: "LINK-CODE" } });
  });

  it("says why a code doesn't work", async () => {
    api.mockRejectedValueOnce(new ApiError(404, "invite_invalid", "invite is unknown"));
    show(<JoinPanel code="OLD" onJoined={() => {}} />);

    expect(await screen.findByText("This invite is unknown, expired, used up or revoked.")).toBeInTheDocument();
    // The code stays to fix and check again.
    expect(screen.getByLabelText("Invite code")).toHaveValue("OLD");
    expect(screen.getByRole("button", { name: "Check" })).toBeEnabled();
  });

  it("says to leave the current main account before joining another", async () => {
    const onJoined = vi.fn();
    api
      .mockResolvedValueOnce(PREVIEW)
      .mockRejectedValueOnce(new ApiError(409, "already_member", "leave first"));
    show(<JoinPanel code="CODE" onJoined={onJoined} />);

    await userEvent.click(await screen.findByRole("button", { name: "Join Riverside School" }));

    expect(await screen.findByText("You already use another main account. Leave it first.")).toBeInTheDocument();
    expect(onJoined).not.toHaveBeenCalled();
  });
});
