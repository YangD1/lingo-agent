import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Card } from "@/lib/vocab";

import en from "../../../messages/en.json";
import { KnownApp } from "./known-app";

const api = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  api,
}));

const card = (id: number, spelling: string, overrides: Partial<Card> = {}): Card => ({
  word: { id, word: spelling, phonetic: null, translation: "adj. 普通的\nn. 公地", definition: null },
  source: "book",
  status: "known",
  due: null,
  last_review: null,
  intervals: [60, 330, 600, 1_296_000],
  sentences: [],
  forms: [],
  ai_examples: [],
  gloss: "adj. 普通的",
  choices: [],
  ...overrides,
});

const COMMON = card(1, "common", {
  last_review: new Date(Date.now() - 2 * 86_400_000).toISOString(),
});
const RELIEF = card(2, "relief", { source: "placement" });
const RELY = card(3, "rely", { source: "auto" });

function show() {
  return render(
    <NextIntlClientProvider locale="en" messages={en} timeZone="UTC">
      <KnownApp />
    </NextIntlClientProvider>,
  );
}

beforeEach(() => api.mockReset());

describe("KnownApp", () => {
  it("lists known words with where they were marked", async () => {
    api.mockResolvedValueOnce({ words: [COMMON, RELIEF, RELY], total: 3 });
    show();
    const list = await screen.findByRole("list", { name: "Known words" });
    expect(within(list).getAllByRole("listitem")).toHaveLength(3);
    expect(api).toHaveBeenCalledWith("/vocab/known?q=&limit=50&offset=0");
    expect(screen.getByTestId("known-common")).toHaveTextContent(
      "Word book · last reviewed 2 days ago",
    );
    expect(screen.getByTestId("known-common")).not.toHaveTextContent("公地");
    expect(screen.getByTestId("known-relief")).toHaveTextContent("Placement test");
    expect(screen.getByTestId("known-rely")).toHaveTextContent("My words");
  });

  it("adds a word back and takes it off the list", async () => {
    api
      .mockResolvedValueOnce({ words: [COMMON, RELIEF], total: 2 })
      .mockResolvedValueOnce(undefined);
    show();
    const row = await screen.findByTestId("known-common");
    await userEvent.click(within(row).getByRole("button", { name: "Review again" }));
    expect(api).toHaveBeenLastCalledWith("/vocab/cards/1/known", { method: "DELETE" });
    await waitFor(() => expect(screen.queryByTestId("known-common")).not.toBeInTheDocument());
    expect(screen.getByRole("status")).toHaveTextContent(
      "“common” is back and will come up in review now.",
    );
    expect(screen.getByTestId("known-relief")).toBeInTheDocument();

    api.mockResolvedValueOnce(undefined);
    await userEvent.click(screen.getByRole("button", { name: "Review again" }));
    expect(await screen.findByText("No known words yet")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("will be learned as a new word");
  });

  it("searches by how the word starts, and pages", async () => {
    api
      .mockResolvedValueOnce({ words: [COMMON], total: 51 })
      .mockResolvedValueOnce({ words: [RELIEF], total: 51 })
      .mockResolvedValueOnce({ words: [RELIEF, RELY], total: 2 })
      .mockResolvedValueOnce({ words: [], total: 0 });
    show();
    await screen.findByTestId("known-common");
    await userEvent.click(screen.getByRole("button", { name: "Show more (50 left)" }));
    expect(await screen.findByTestId("known-relief")).toBeInTheDocument();
    expect(api).toHaveBeenLastCalledWith("/vocab/known?q=&limit=50&offset=1");

    await userEvent.type(screen.getByRole("searchbox", { name: "Search words" }), "rel");
    await waitFor(() => expect(screen.queryByTestId("known-common")).not.toBeInTheDocument());
    expect(api).toHaveBeenLastCalledWith("/vocab/known?q=rel&limit=50&offset=0");
    expect(screen.getByTestId("known-rely")).toBeInTheDocument();

    await userEvent.type(screen.getByRole("searchbox"), "x");
    expect(await screen.findByText("No known words start with “relx”.")).toBeInTheDocument();
  });
});
