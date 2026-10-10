import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import type { WordAudio, WordAudioEstimate, WordAudioJob } from "@/lib/types";

import en from "../../../messages/en.json";
import { WordAudioSection } from "./word-audio-section";

const api = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  api,
}));

const SONIA = { connection: "azure", model: "en-US-AvaMultilingualNeural", voice: "en-GB-SoniaNeural" };
const AVA = { connection: "azure", model: "en-US-AvaMultilingualNeural", voice: "en-US-AvaMultilingualNeural" };

function state(job: WordAudioJob | null = null, extra: Partial<WordAudio> = {}): WordAudio {
  return {
    available: true,
    voices: { "en-US": AVA, "en-GB": SONIA },
    job,
    books: [
      { book_id: "cet4", name_zh: "大学英语四级", name_en: "CET-4", words: 3849, made: { "en-US": 0, "en-GB": 0 } },
      { book_id: "gre", name_zh: "GRE", name_en: "GRE", words: 7504, made: { "en-US": 120, "en-GB": 0 } },
    ],
    count: 120,
    bytes: 840_000,
    old_count: 0,
    old_bytes: 0,
    ...extra,
  };
}

const ESTIMATE: WordAudioEstimate = {
  book_id: "cet4",
  words: 3849,
  voices: { "en-US": AVA, "en-GB": SONIA },
  missing: [],
  pieces: 7698,
  existing: 0,
  characters: 61_000,
  bytes: 53_886_000,
  cost: 0.915,
  requests_per_minute: 20,
  suggested_price: 15,
  minutes: 385,
};

function job(status: WordAudioJob["status"], extra: Partial<WordAudioJob> = {}): WordAudioJob {
  return {
    id: "j1",
    book_id: "cet4",
    status,
    voices: { "en-US": AVA },
    requests_per_minute: 20,
    price_per_million: 15,
    currency: "USD",
    total: 3849,
    done: 1000,
    failed: 2,
    characters: 8000,
    bytes: 7_000_000,
    cost: 0.12,
    error: null,
    created_at: "2026-10-10T08:00:00Z",
    finished_at: null,
    ...extra,
  };
}

function show() {
  return render(
    <NextIntlClientProvider locale="en" messages={en} timeZone="UTC">
      <WordAudioSection />
    </NextIntlClientProvider>,
  );
}

beforeEach(() => {
  api.mockReset(); // in a block: a function returned from beforeEach runs as cleanup
});

describe("WordAudioSection", () => {
  it("is hidden from learners who aren't admins", async () => {
    api.mockRejectedValue(new ApiError(403, "forbidden", "no"));
    const { container } = show();
    await waitFor(() => expect(api).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it("estimates a book with Azure's suggested price and pace, then starts it", async () => {
    let current = state();
    api.mockImplementation(async (path: string, init?: { method?: string; json?: unknown }) => {
      if (path === "/tenant/word-audio") return current;
      if (path.startsWith("/tenant/word-audio/estimate")) return ESTIMATE;
      if (path === "/tenant/word-audio/jobs") {
        current = state(job("running"));
        return current.job;
      }
      throw new Error(`unexpected ${path} ${init?.method}`);
    });
    show();

    await userEvent.click(await screen.findByRole("button", { name: "Generate pronunciations for CET-4" }));
    const form = await screen.findByRole("form", { name: "Generate word pronunciations" });
    await within(form).findByText(/7,698 pieces of audio, 0 already there, 7,698 to generate/);
    expect(within(form).getByLabelText("Price per million characters")).toHaveValue(15);
    expect(within(form).getByLabelText("Currency")).toHaveValue("USD");
    expect(within(form).getByLabelText("Requests per minute")).toHaveValue(20);
    expect(within(form).getByText(/About 61,000 characters, 51.4 MB, 385 minutes · about 0.915 USD/)).toBeInTheDocument();
    expect(api).toHaveBeenCalledWith(
      "/tenant/word-audio/estimate?book_id=cet4&accents=en-US&accents=en-GB",
    );

    await userEvent.click(within(form).getByRole("button", { name: "Start" }));

    expect(api).toHaveBeenCalledWith("/tenant/word-audio/jobs", {
      method: "POST",
      json: {
        book_id: "cet4",
        accents: ["en-US", "en-GB"],
        requests_per_minute: 20,
        price_per_million: 15,
        currency: "USD",
      },
    });
    expect(await screen.findByRole("heading", { name: "CET-4 · Generating" })).toBeInTheDocument();
    expect(screen.getByText("1,000 of 3,849 done, 2 failed")).toBeInTheDocument();
    // One job at a time.
    expect(screen.getByRole("button", { name: "Generate pronunciations for GRE" })).toBeDisabled();
  });

  it("pauses a running job and shows why one paused by itself", async () => {
    let current = state(job("running"));
    api.mockImplementation(async (path: string) => {
      if (path === "/tenant/word-audio/jobs/current/pause") {
        current = state(job("paused", { error: "20 words in a row failed" }));
        return current.job;
      }
      return current;
    });
    show();

    await userEvent.click(await screen.findByRole("button", { name: "Pause" }));

    expect(await screen.findByRole("button", { name: "Resume" })).toBeInTheDocument();
    expect(screen.getByText("Paused by itself: 20 words in a row failed")).toBeInTheDocument();
    expect(api).toHaveBeenCalledWith("/tenant/word-audio/jobs/current/pause", { method: "POST" });
  });

  it("deletes a book's audio and audio in old voices after asking", async () => {
    let current = state(null, { old_count: 40, old_bytes: 2 * 1024 * 1024 });
    api.mockImplementation(async (path: string, init?: { method?: string }) => {
      if (init?.method === "DELETE") {
        current = state();
        return { deleted: path.includes("old") ? 40 : 120, bytes: 0 };
      }
      return current;
    });
    show();

    expect(await screen.findByText("40 of them (2 MB) are in a voice no longer used.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Delete old voices" }));
    await userEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(api).toHaveBeenCalledWith("/tenant/word-audio?old=true", { method: "DELETE" });
    expect(await screen.findByText("Deleted 40 pronunciations.")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Delete the pronunciations of GRE" }));
    await userEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(api).toHaveBeenCalledWith("/tenant/word-audio?book_id=gre", { method: "DELETE" });
    // Nothing made for CET-4: nothing to delete.
    expect(screen.queryByRole("button", { name: "Delete the pronunciations of CET-4" })).toBeNull();
  });

  it("says to set up a read-aloud model first", async () => {
    api.mockResolvedValue(state(null, { available: false, voices: {} }));
    show();
    expect(await screen.findByText(/No read-aloud model reads English yet/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Generate pronunciations for CET-4" })).toBeDisabled();
  });
});
