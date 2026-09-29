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
        json: { models: ["relay:chat-model"] },
      }),
    );
  });
});
