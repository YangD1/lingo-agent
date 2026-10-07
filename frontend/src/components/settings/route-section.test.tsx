import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Connection, TaskRoute } from "@/lib/types";

import en from "../../../messages/en.json";
import { RouteSection, type RouteTask } from "./route-section";

const api = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  api,
}));

const route = (overrides: Partial<TaskRoute>): TaskRoute => ({
  section: "llm",
  task: "chat",
  models: [],
  params: {},
  disabled: [],
  overridden: false,
  effective: [],
  effective_source: null,
  ...overrides,
});

const ROUTES: TaskRoute[] = [
  route({ task: "chat", effective: ["relay:chat-model"], effective_source: "auto" }),
  route({ task: "reflect" }),
  // Vision has no automatic fallback (ADR 0008 §5): nothing configured, nothing runs.
  route({ task: "vision" }),
  route({
    section: "asr",
    task: "default",
    models: ["groq:whisper-large-v3-turbo"],
    overridden: true,
    effective: ["groq:whisper-large-v3-turbo"],
    effective_source: "override",
  }),
];

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

function show(task: RouteTask, connections: Connection[] = []) {
  return render(
    <NextIntlClientProvider locale="en" messages={en}>
      <RouteSection task={task} connections={connections} />
    </NextIntlClientProvider>,
  );
}

beforeEach(() => {
  api.mockReset();
  api.mockImplementation(async (path: string) => (path === "/tenant/routes" ? ROUTES : undefined));
});

describe("RouteSection", () => {
  it("says when the vision route is not set up", async () => {
    show("vision");

    expect(await screen.findByTestId("route-source-vision")).toHaveTextContent(
      "Not set up: images and scanned PDFs can't be read",
    );
    expect(screen.getByText("Image model (vision)")).toBeInTheDocument();
  });

  it("edits the asr section's single route", async () => {
    show("asr");

    expect(await screen.findByRole("list", { name: "Speech-to-text" })).toHaveTextContent(
      "groq:whisper-large-v3-turbo",
    );
    await userEvent.click(screen.getByRole("button", { name: "Reset to default" }));

    await waitFor(() =>
      expect(api).toHaveBeenCalledWith("/tenant/routes/asr/default", { method: "DELETE" }),
    );
  });

  it("keeps showing the chat route and where it comes from", async () => {
    show("chat");

    expect(await screen.findByTestId("route-source-chat")).toHaveTextContent("Automatic");
    expect(screen.getByRole("list", { name: "Chat model" })).toHaveTextContent("relay:chat-model");
  });

  it("sets the background memory model, starting from the connection's chat model", async () => {
    show("reflect", [RELAY]);

    expect(await screen.findByText("Background memory model")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Edit order" }));
    expect(screen.getByRole("combobox", { name: "Model 1" })).toHaveValue("chat-model");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(api).toHaveBeenCalledWith("/tenant/routes/llm/reflect", {
        method: "PUT",
        json: { models: ["relay:chat-model"], disabled: [] },
      }),
    );
  });

  // --- switching models off (ADR 0026) ----------------------------------------------

  it("switches a row off at once, saving the chain that was shown", async () => {
    const OPENAI: Connection = { ...RELAY, id: "c2", name: "openai" };
    const chat = route({
      task: "chat",
      effective: ["relay:a", "openai:b"],
      effective_source: "auto",
    });
    api.mockImplementation(async (path: string, init?: { method?: string }) => {
      if (path === "/tenant/routes") return [chat];
      if (init?.method === "PUT")
        return route({
          task: "chat",
          models: ["relay:a", "openai:b"],
          disabled: ["relay:a"],
          overridden: true,
          effective: ["openai:b"],
          effective_source: "override",
        });
    });
    show("chat", [RELAY, OPENAI]);

    await userEvent.click(await screen.findByRole("switch", { name: "Use relay:a" }));

    expect(api).toHaveBeenCalledWith("/tenant/routes/llm/chat", {
      method: "PUT",
      json: { models: ["relay:a", "openai:b"], disabled: ["relay:a"] },
    });
    expect(await screen.findByRole("switch", { name: "Use relay:a" })).not.toBeChecked();
    expect(screen.getByRole("status")).toHaveTextContent("relay:a is off");
    const [first, second] = screen.getAllByRole("listitem");
    expect(first).toHaveAttribute("data-state", "off");
    expect(first).toHaveTextContent("Off");
    // The first row that runs is the primary now, not a fallback.
    expect(second).toHaveAttribute("data-state", "on");
    expect(second).not.toHaveTextContent("Fallback");
  });

  it("marks rows whose connection is off or gone, and says when nothing is left", async () => {
    const OFF: Connection = { ...RELAY, id: "c2", name: "openai", enabled: false };
    const chat = route({
      task: "chat",
      models: ["relay:a", "openai:b", "gone:c"],
      disabled: ["relay:a"],
      overridden: true,
      effective: [],
      effective_source: null,
    });
    api.mockImplementation(async (path: string) => (path === "/tenant/routes" ? [chat] : undefined));
    show("chat", [RELAY, OFF]);

    expect(await screen.findByText(/Every model here is switched off/)).toBeInTheDocument();
    const rows = screen.getAllByRole("listitem");
    expect(rows.map((r) => r.getAttribute("data-state"))).toEqual([
      "off",
      "connectionOff",
      "connectionMissing",
    ]);
    expect(rows[1]).toHaveTextContent("Connection off");
    expect(rows[2]).toHaveTextContent("Connection deleted");
  });

  it("keeps switched-off rows when the order is edited", async () => {
    const OPENAI: Connection = { ...RELAY, id: "c2", name: "openai" };
    const chat = route({
      task: "chat",
      models: ["relay:a", "openai:b"],
      disabled: ["openai:b"],
      overridden: true,
      effective: ["relay:a"],
      effective_source: "override",
    });
    api.mockImplementation(async (path: string) => (path === "/tenant/routes" ? [chat] : undefined));
    show("chat", [RELAY, OPENAI]);

    await userEvent.click(await screen.findByRole("button", { name: "Edit order" }));
    expect(screen.getByRole("switch", { name: "Use openai:b" })).not.toBeChecked();
    await userEvent.click(screen.getAllByRole("button", { name: "Move up" })[1]);
    await userEvent.click(screen.getByRole("switch", { name: "Use relay:a" }));
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(api).toHaveBeenCalledWith("/tenant/routes/llm/chat", {
        method: "PUT",
        json: { models: ["openai:b", "relay:a"], disabled: ["openai:b", "relay:a"] },
      }),
    );
  });
});
