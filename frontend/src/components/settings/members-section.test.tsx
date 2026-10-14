import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import type { Invite, Member, QuotaUsage, Quotas } from "@/lib/org";

import en from "../../../messages/en.json";
import { MembersSection } from "./members-section";

const api = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  api,
}));

const QUOTAS: Quotas = {
  text: { daily: 50_000, monthly: 1_000_000 },
  tts: { daily: null, monthly: 200_000 },
  asr: { daily: 30, monthly: null },
  pronunciation: { daily: 0, monthly: 0 },
  realtime: { daily: 10, monthly: 60 },
};
const nothing = { day: 0, month: 0 };
const USAGE: QuotaUsage = {
  text: { day: 50_000, month: 120_000 },
  tts: nothing,
  asr: { day: 2.5, month: 2.5 },
  pronunciation: nothing,
  realtime: nothing,
};

const ALEX: Member = {
  id: "m1",
  display_name: "Alex",
  email: "alex@example.com",
  status: "active",
  joined_at: "2026-10-12T08:00:00Z",
  ended_at: null,
  quotas: QUOTAS,
  usage: USAGE,
};
const SAM: Member = { ...ALEX, id: "m2", display_name: null, email: "sam@example.com", status: "left" };
const INVITE: Invite = {
  id: "i1",
  expires_at: "2026-10-19T08:00:00Z",
  max_uses: 1,
  used_count: 0,
  created_at: "2026-10-12T08:00:00Z",
};

function show() {
  return render(
    <NextIntlClientProvider locale="en" messages={en} timeZone="UTC">
      <MembersSection />
    </NextIntlClientProvider>,
  );
}

function backend({ members = [ALEX, SAM], invites = [INVITE] }: { members?: Member[]; invites?: Invite[] } = {}) {
  api.mockImplementation(async (path: string, init?: { method?: string }) => {
    if (path === "/org/members") return members;
    if (path === "/org/invites" && init?.method === "POST") return { ...INVITE, id: "i2", code: "SECRET-CODE" };
    if (path === "/org/invites") return invites;
    if (path === "/org/default-quotas") return QUOTAS;
    return undefined;
  });
}

beforeEach(() => api.mockReset());

describe("MembersSection", () => {
  it("is hidden from people who don't manage the account", async () => {
    const forbidden = new ApiError(403, "forbidden", "no");
    api.mockRejectedValueOnce(forbidden).mockRejectedValueOnce(forbidden);
    const { container } = show();

    await waitFor(() => expect(api).toHaveBeenCalledWith("/org/members"));
    expect(container).toBeEmptyDOMElement();
  });

  it("lists members with their use against their caps, and past members apart", async () => {
    backend();
    show();

    const row = await screen.findByTestId("member-row");
    expect(row).toHaveTextContent("Alex");
    expect(row).toHaveTextContent("alex@example.com · joined Oct 12, 2026");
    const usage = within(row).getByRole("table", { name: "Use by Alex" });
    const text = within(usage).getByRole("row", { name: /Chat and text/ });
    expect(text).toHaveTextContent("50,000 / 50,000");
    expect(within(text).getByText("50,000 / 50,000")).toHaveClass("text-destructive");
    expect(within(usage).getByRole("row", { name: /Pronunciation/ })).toHaveTextContent("OffOff");
    expect(within(usage).getByRole("row", { name: /Read aloud/ })).toHaveTextContent("0 / No cap");
    expect(screen.getByText("1 past member")).toBeInTheDocument();
    expect(screen.getByText("Left")).toBeInTheDocument();
    expect(screen.getByText("Expires Oct 19, 2026, 8:00 AM · used 0 / 1")).toBeInTheDocument();
  });

  it("creates an invite and shows its link once", async () => {
    backend({ invites: [] });
    show();

    await userEvent.click(await screen.findByRole("radio", { name: "30 days" }));
    await userEvent.clear(screen.getByLabelText("Uses"));
    await userEvent.click(screen.getByRole("button", { name: "Create invite link" }));

    expect(api).toHaveBeenCalledWith("/org/invites", { method: "POST", json: { days: 30, max_uses: null } });
    expect(await screen.findByLabelText("Invite link")).toHaveValue(
      `${window.location.origin}/join?code=SECRET-CODE`,
    );
    expect(screen.getByText("Code: SECRET-CODE")).toBeInTheDocument();
  });

  it("won't create an invite with a bad number of uses", async () => {
    backend();
    show();

    const uses = await screen.findByLabelText("Uses");
    await userEvent.clear(uses);
    await userEvent.type(uses, "0");

    expect(screen.getByRole("button", { name: "Create invite link" })).toBeDisabled();
  });

  it("revokes an invite after asking", async () => {
    backend();
    show();

    await userEvent.click(await screen.findByRole("button", { name: "Revoke" }));
    await userEvent.click(
      within(screen.getByRole("group", { name: /Revoke this invite/ })).getByRole("button", { name: "Revoke" }),
    );

    await waitFor(() => expect(api).toHaveBeenCalledWith("/org/invites/i1", { method: "DELETE" }));
  });

  it("edits a member's quotas: empty is no cap, 0 is off", async () => {
    backend();
    show();

    const row = await screen.findByTestId("member-row");
    await userEvent.click(within(row).getByRole("button", { name: "Edit quotas" }));
    const daily = within(row).getByLabelText("Chat and text · Daily cap");
    expect(daily).toHaveValue(50000);
    await userEvent.clear(daily);
    const calls = within(row).getByLabelText("Voice calls · Monthly cap");
    await userEvent.clear(calls);
    await userEvent.type(calls, "0");
    await userEvent.click(within(row).getByRole("button", { name: "Save" }));

    expect(api).toHaveBeenCalledWith("/org/members/m1/quotas", {
      method: "PUT",
      json: {
        ...QUOTAS,
        text: { daily: null, monthly: 1_000_000 },
        realtime: { daily: 10, monthly: 0 },
      },
    });
  });

  it("removes a member after asking", async () => {
    backend();
    show();

    await userEvent.click(await screen.findByRole("button", { name: "Remove" }));
    await userEvent.click(
      within(screen.getByRole("group", { name: /Remove Alex\?/ })).getByRole("button", { name: "Remove" }),
    );

    await waitFor(() => expect(api).toHaveBeenCalledWith("/org/members/m1", { method: "DELETE" }));
  });

  it("saves the quotas new members start with", async () => {
    backend({ members: [] });
    show();

    expect(await screen.findByText(/No members yet/)).toBeInTheDocument();
    await userEvent.click(await screen.findByText("Quotas for new members"));
    const tts = await screen.findByLabelText("Read aloud · Daily cap");
    await userEvent.type(tts, "5000");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(api).toHaveBeenCalledWith("/org/default-quotas", {
      method: "PUT",
      json: { ...QUOTAS, tts: { daily: 5000, monthly: 200_000 } },
    });
    expect(await screen.findByText("Saved.")).toBeInTheDocument();
  });
});
