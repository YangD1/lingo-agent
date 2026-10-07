import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Connection } from "@/lib/types";

import en from "../../../messages/en.json";
import { ConnectionsSection } from "./connections-section";

const api = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  api,
}));

const RELAY: Connection = {
  id: "c1",
  name: "relay",
  kind: "openai_compatible",
  base_url: "https://relay.example.com/v1",
  has_api_key: true,
  key_hint: "…1234",
  params: {},
  enabled: true,
  default_model: "chat-model",
  last_verified_at: null,
  last_error: null,
};

function Harness({ initial }: { initial: Connection[] }) {
  const [connections, setConnections] = useState(initial);
  return (
    <ConnectionsSection
      presets={{ presets: [], allow_private_networks: false }}
      connections={connections}
      onChange={setConnections}
    />
  );
}

function show(initial: Connection[]) {
  return render(
    <NextIntlClientProvider locale="en" messages={en}>
      <Harness initial={initial} />
    </NextIntlClientProvider>,
  );
}

beforeEach(() => {
  api.mockReset();
  api.mockImplementation(async (path: string, init?: { json?: { enabled?: boolean } }) =>
    path === "/tenant/connections/c1" ? { ...RELAY, enabled: init?.json?.enabled } : undefined,
  );
});

describe("ConnectionsSection", () => {
  it("switches a connection off, keeping it and its settings, and back on", async () => {
    show([RELAY]);
    const item = screen.getByTestId("connection-relay");
    const toggle = screen.getByRole("switch", { name: "Use relay" });
    expect(toggle).toBeChecked();

    await userEvent.click(toggle);

    expect(api).toHaveBeenCalledWith("/tenant/connections/c1", {
      method: "PATCH",
      json: { enabled: false },
    });
    await waitFor(() => expect(item).toHaveAttribute("data-enabled", "false"));
    expect(screen.getByRole("switch", { name: "Use relay" })).not.toBeChecked();
    expect(item).toHaveTextContent("Off: no feature uses this connection");
    expect(item).toHaveTextContent("https://relay.example.com/v1");
    expect(item).toHaveTextContent("Connection turned off.");

    await userEvent.click(screen.getByRole("switch", { name: "Use relay" }));

    await waitFor(() => expect(item).toHaveAttribute("data-enabled", "true"));
    expect(item).not.toHaveTextContent("Off: no feature uses this connection");
    expect(item).toHaveTextContent("Connection turned on.");
  });
});
