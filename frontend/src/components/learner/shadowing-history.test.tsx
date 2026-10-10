import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ShadowingResult } from "@/lib/shadowing";

import en from "../../../messages/en.json";
import { ShadowingHistory } from "./shadowing-history";

const api = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  api,
}));
const shadowing = vi.hoisted(() => ({ mode: "assessment" as "assessment" | "rough" | null }));
vi.mock("@/lib/shadowing", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/shadowing")>()),
  useShadowingMode: () => shadowing.mode,
}));
vi.mock("@/lib/ai-usage", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/ai-usage")>()),
  loadEstimates: () => new Promise(() => {}),
}));

const reading = (id: string, over: Partial<ShadowingResult> = {}): ShadowingResult => ({
  id,
  source: "chat",
  source_id: "m1",
  reference_text: `Sentence ${id}.`,
  language: "en-US",
  mode: "assessment",
  fallback_reason: null,
  scores: { overall: 82, accuracy: 80, fluency: 85, completeness: 100, prosody: 70 },
  words: [],
  recognized_text: "",
  audio_seconds: 2,
  counted: true,
  created_at: "2026-10-10T08:00:00Z",
  mispronounced: [],
  ...over,
});

function show() {
  return render(
    <NextIntlClientProvider locale="en" messages={en} timeZone="UTC">
      <ShadowingHistory />
    </NextIntlClientProvider>,
  );
}

beforeEach(() => {
  api.mockReset();
  shadowing.mode = "assessment";
});

describe("ShadowingHistory", () => {
  it("shows nothing with neither readings nor a way to shadow", async () => {
    shadowing.mode = null;
    api.mockResolvedValue({ items: [], next_before: null });
    show();
    await waitFor(() => expect(api).toHaveBeenCalled());
    expect(screen.queryByTestId("learner-shadowing")).not.toBeInTheDocument();
  });

  it("points to where shadowing starts while there are no readings", async () => {
    api.mockResolvedValue({ items: [], next_before: null });
    show();
    expect(await screen.findByText(/No readings yet/)).toBeInTheDocument();
  });

  it("lists readings with their scores, rough ones marked, and loads earlier ones", async () => {
    api
      .mockResolvedValueOnce({
        items: [
          reading("a", { mispronounced: ["think"] }),
          reading("b", {
            source: "reading",
            mode: "rough",
            scores: null,
            words: [
              { word: "I", error: "none" },
              { word: "so", error: "omission" },
            ],
          }),
        ],
        next_before: "2026-10-09T00:00:00Z",
      })
      .mockResolvedValueOnce({ items: [reading("c", { source: "vocab" })], next_before: null });
    show();
    const items = await screen.findAllByTestId("shadowing-item");
    expect(items[0]).toHaveTextContent("82");
    expect(items[0]).toHaveTextContent("Tutor chat · off: think");
    expect(items[1]).toHaveTextContent("1/2");
    expect(items[1]).toHaveTextContent("rough");
    expect(items[1]).toHaveTextContent("Reading");

    await userEvent.click(screen.getByRole("button", { name: "Load earlier" }));
    expect(api).toHaveBeenLastCalledWith(
      `/speech/shadowing?limit=20&before=${encodeURIComponent("2026-10-09T00:00:00Z")}`,
    );
    expect(await screen.findAllByTestId("shadowing-item")).toHaveLength(3);
    expect(screen.queryByRole("button", { name: "Load earlier" })).not.toBeInTheDocument();
  });

  it("deletes one reading after asking", async () => {
    api.mockResolvedValueOnce({ items: [reading("a"), reading("b")], next_before: null });
    show();
    const [first] = await screen.findAllByTestId("shadowing-item");
    await userEvent.click(within(first).getByRole("button", { name: "Delete this reading" }));
    api.mockResolvedValueOnce(undefined);
    await userEvent.click(within(first).getByRole("button", { name: "Delete" }));
    expect(api).toHaveBeenLastCalledWith("/speech/shadowing/a", { method: "DELETE" });
    await waitFor(() => expect(screen.getAllByTestId("shadowing-item")).toHaveLength(1));
  });

  it("clears every reading after confirming", async () => {
    api.mockResolvedValueOnce({ items: [reading("a")], next_before: null });
    show();
    await screen.findAllByTestId("shadowing-item");
    await userEvent.click(screen.getByRole("button", { name: "Clear shadowing history" }));
    api.mockResolvedValueOnce({ deleted: 1 });
    const dialog = await screen.findByRole("alertdialog");
    await userEvent.click(within(dialog).getByRole("button", { name: /Delete|Clear/ }));
    expect(api).toHaveBeenLastCalledWith("/speech/shadowing", { method: "DELETE" });
    expect(await screen.findByText(/No readings yet/)).toBeInTheDocument();
  });
});
