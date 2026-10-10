import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Connection, Presets } from "@/lib/types";

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

const NO_PRESETS: Presets = { presets: [], allow_private_networks: false };
const AZURE_PRESET: Presets = {
  presets: [
    {
      name: "azure",
      kind: "azure_speech",
      label: "Azure Speech (read aloud)",
      base_url: "https://eastasia.tts.speech.microsoft.com",
      models: ["en-US-AvaMultilingualNeural"],
    },
  ],
  allow_private_networks: false,
};
const AZURE: Connection = {
  ...RELAY,
  id: "c2",
  name: "azure",
  kind: "azure_speech",
  base_url: "https://chinaeast2.tts.speech.azure.cn",
  default_model: null,
};

function Harness({ initial, presets }: { initial: Connection[]; presets: Presets }) {
  const [connections, setConnections] = useState(initial);
  return (
    <ConnectionsSection
      presets={presets}
      connections={connections}
      onChange={setConnections}
    />
  );
}

function show(initial: Connection[], presets = NO_PRESETS) {
  return render(
    <NextIntlClientProvider locale="en" messages={en}>
      <Harness initial={initial} presets={presets} />
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

  it("adds Azure Speech in the region given, China's on azure.cn", async () => {
    api.mockResolvedValueOnce(AZURE);
    show([], AZURE_PRESET);
    expect(screen.getByText("https://eastasia.tts.speech.microsoft.com")).toBeInTheDocument();

    await userEvent.type(screen.getByLabelText("Region"), "ChinaEast2");
    await userEvent.click(screen.getByLabelText("Azure China (azure.cn)"));
    expect(screen.getByText("https://chinaeast2.tts.speech.azure.cn")).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("API key"), "azure-key-0123456789");
    await userEvent.click(screen.getByRole("button", { name: "Add connection" }));

    expect(api).toHaveBeenCalledWith("/tenant/connections", {
      method: "POST",
      json: {
        preset: "azure",
        api_key: "azure-key-0123456789",
        base_url: "https://chinaeast2.tts.speech.azure.cn",
      },
    });
  });

  it("tests a read-aloud connection with a voice, and says when it can't read aloud", async () => {
    api.mockImplementation(async (path: string) =>
      path.endsWith("/test")
        ? { ok: false, error: "404", error_code: "tts_not_supported", latency_ms: 80, purpose: "tts" }
        : [AZURE],
    );
    show([AZURE], AZURE_PRESET);
    const item = screen.getByTestId("connection-azure");
    // Speech only: no default chat model to save, the box is the voice to test.
    expect(screen.getByLabelText("Model to test")).toHaveValue("en-US-AvaMultilingualNeural");
    expect(screen.queryByRole("button", { name: "Save model" })).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Test" }));

    expect(api).toHaveBeenCalledWith("/tenant/connections/c2/test", {
      method: "POST",
      json: { model: "en-US-AvaMultilingualNeural" },
    });
    await waitFor(() => expect(item).toHaveTextContent("This connection can't read aloud"));
  });

  it("tests pronunciation assessment on the same connection", async () => {
    api.mockImplementation(async (path: string) =>
      path.endsWith("/test")
        ? { ok: true, error: null, error_code: null, latency_ms: 120, purpose: "pronunciation" }
        : [AZURE],
    );
    show([AZURE], AZURE_PRESET);
    const item = screen.getByTestId("connection-azure");
    const model = screen.getByLabelText("Model to test");
    await userEvent.clear(model);
    await userEvent.type(model, "pronunciation");
    await userEvent.keyboard("{Escape}");

    await userEvent.click(screen.getByRole("button", { name: "Test" }));

    expect(api).toHaveBeenCalledWith("/tenant/connections/c2/test", {
      method: "POST",
      json: { model: "pronunciation" },
    });
    await waitFor(() => expect(item).toHaveTextContent("Pronunciation assessment works (120 ms)"));
    expect(screen.getByRole("option", { name: "Pronunciation" })).toBeInTheDocument();
  });
});
