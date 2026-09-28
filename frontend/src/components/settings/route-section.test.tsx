import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { TaskRoute } from "@/lib/types";

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

function show(task: RouteTask) {
  return render(
    <NextIntlClientProvider locale="en" messages={en}>
      <RouteSection task={task} connections={[]} />
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
});
