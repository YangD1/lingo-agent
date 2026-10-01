import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import type { Card } from "@/lib/vocab";

import en from "../../../messages/en.json";
import { MineApp } from "./mine-app";

const api = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  api,
}));

const card = (id: number, spelling: string, overrides: Partial<Card> = {}): Card => ({
  word: { id, word: spelling, phonetic: null, translation: "v. 去\nn. 尝试", definition: null },
  source: "manual",
  status: "new",
  due: null,
  last_review: null,
  intervals: [60, 330, 600, 1_296_000],
  ...overrides,
});

const GO = card(1, "go");
const RELUCTANT = card(2, "reluctant", {
  source: "auto",
  status: "learning",
  due: new Date(Date.now() + 3 * 86_400_000).toISOString(),
});

function show() {
  return render(
    <NextIntlClientProvider locale="en" messages={en} timeZone="UTC">
      <MineApp />
    </NextIntlClientProvider>,
  );
}

beforeEach(() => api.mockReset());

describe("MineApp", () => {
  it("lists the words with where they came from and when they are due", async () => {
    api.mockResolvedValueOnce({ words: [RELUCTANT, GO], total: 2 });
    show();
    const list = await screen.findByRole("list", { name: "My words" });
    expect(within(list).getAllByRole("listitem")).toHaveLength(2);
    expect(screen.getByTestId("mine-reluctant")).toHaveTextContent(
      "Picked up in conversation · Learning · next review in 3 days",
    );
    expect(screen.getByTestId("mine-go")).toHaveTextContent("v. 去");
    expect(screen.getByTestId("mine-go")).not.toHaveTextContent("尝试");
    expect(screen.getByTestId("mine-go")).toHaveTextContent("Added by you · Not started");
  });

  it("adds a word, saying when it was turned into its base form", async () => {
    api
      .mockResolvedValueOnce({ words: [], total: 0 })
      .mockResolvedValueOnce({ card: GO, matched: "lemma", added: true })
      .mockResolvedValueOnce({ words: [GO], total: 1 })
      .mockRejectedValueOnce(new ApiError(404, "word_not_found", "no such word"));
    show();
    expect(await screen.findByText("Your word list is empty")).toBeInTheDocument();

    const input = screen.getByRole("combobox", { name: "Add a word" });
    await userEvent.type(input, "went{Enter}");
    expect(api).toHaveBeenCalledWith("/vocab/mine", { method: "POST", json: { word: "went" } });
    expect(await screen.findByRole("status")).toHaveTextContent(
      "Added “go” (the base form of “went”).",
    );
    expect(await screen.findByTestId("mine-go")).toBeInTheDocument();
    expect(input).toHaveValue("");

    await userEvent.type(input, "wented{Enter}");
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The dictionary doesn't have this word.",
    );
  });

  it("suggests dictionary words while typing", async () => {
    api.mockResolvedValueOnce({ words: [], total: 0 }).mockResolvedValue([card(3, "reluctant").word]);
    show();
    await userEvent.type(await screen.findByRole("combobox", { name: "Add a word" }), "relu");
    await waitFor(() => expect(api).toHaveBeenCalledWith("/vocab/words?q=relu"));
    expect(await screen.findByRole("option", { name: "reluctant" })).toBeInTheDocument();
  });

  it("removes a word after confirming", async () => {
    api
      .mockResolvedValueOnce({ words: [GO], total: 1 })
      .mockResolvedValueOnce(undefined)
      .mockResolvedValueOnce({ words: [], total: 0 });
    show();
    const row = await screen.findByTestId("mine-go");
    // The button turns into the question with Delete / Cancel in its place.
    await userEvent.click(within(row).getByRole("button", { name: "Remove" }));
    expect(within(row).getByRole("group")).toHaveTextContent("review history");
    await userEvent.click(within(row).getByRole("button", { name: "Cancel" }));
    expect(api).toHaveBeenCalledTimes(1);
    await userEvent.click(within(row).getByRole("button", { name: "Remove" }));
    await userEvent.click(within(row).getByRole("button", { name: "Delete" }));
    expect(api).toHaveBeenCalledWith("/vocab/mine/1", { method: "DELETE" });
    expect(await screen.findByText("Your word list is empty")).toBeInTheDocument();
  });

  it("loads more", async () => {
    api
      .mockResolvedValueOnce({ words: [GO], total: 2 })
      .mockResolvedValueOnce({ words: [RELUCTANT], total: 2 });
    show();
    await userEvent.click(await screen.findByRole("button", { name: "Show more (1 left)" }));
    expect(api).toHaveBeenLastCalledWith("/vocab/mine?limit=50&offset=1");
    expect(await screen.findByTestId("mine-reluctant")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Show more/ })).not.toBeInTheDocument();
  });
});
