import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { BookProgress, VocabOverview } from "@/lib/vocab";

import en from "../../../messages/en.json";
import { VocabApp } from "./vocab-app";

const api = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  api,
}));

const book = (id: string, overrides: Partial<BookProgress> = {}): BookProgress => ({
  id,
  name_zh: id,
  name_en: id.toUpperCase(),
  total: 4000,
  learning: 0,
  known: 0,
  ...overrides,
});

const overview = (overrides: Partial<VocabOverview> = {}): VocabOverview => ({
  books: [book("oxford3000"), book("cet4", { learning: 120, known: 480 })],
  book_id: null,
  daily_new: null,
  daily_new_default: 15,
  screened: false,
  today: { reviews_due: 0, new_left: 0, new_limit: 15, new_started: 0 },
  ...overrides,
});

function show() {
  return render(
    <NextIntlClientProvider locale="en" messages={en}>
      <VocabApp />
    </NextIntlClientProvider>,
  );
}

beforeEach(() => api.mockReset());

describe("VocabApp", () => {
  it("asks a new learner to pick a book, and picking one reloads", async () => {
    api
      .mockResolvedValueOnce(overview())
      .mockResolvedValueOnce(undefined)
      .mockResolvedValueOnce(
        overview({
          book_id: "oxford3000",
          today: { reviews_due: 0, new_left: 15, new_limit: 15, new_started: 0 },
        }),
      );
    show();
    expect(await screen.findByText(/No word book chosen yet/)).toBeInTheDocument();
    expect(api.mock.calls[0]![0]).toMatch(/^\/vocab\?tz=/);
    expect(screen.queryByRole("link", { name: "Start" })).not.toBeInTheDocument();
    expect(screen.queryByText("New words a day")).not.toBeInTheDocument();

    const oxford = screen.getByTestId("book-oxford3000");
    await userEvent.click(within(oxford).getByRole("button", { name: "Study this book" }));
    expect(api).toHaveBeenCalledWith("/vocab/book", {
      method: "PUT",
      json: { book_id: "oxford3000", daily_new: null },
    });
    expect(await within(oxford).findByText("Current")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Start" })).toHaveAttribute("href", "/vocab/review");
    expect(screen.getByRole("link", { name: "Screen known words" })).toHaveAttribute(
      "href",
      "/vocab/screen",
    );
    expect(screen.getByText(/screen the book first/)).toBeInTheDocument();
  });

  it("shows today's work and each book's progress", async () => {
    api.mockResolvedValueOnce(
      overview({
        book_id: "cet4",
        screened: true,
        today: { reviews_due: 30, new_left: 5, new_limit: 15, new_started: 10 },
      }),
    );
    show();
    expect(await screen.findByTestId("today-counts")).toHaveTextContent(
      "30 to review · 5 new words left (started 10 of 15 today)",
    );
    expect(screen.getByRole("link", { name: "New words only" })).toHaveAttribute(
      "href",
      "/vocab/review?mode=new",
    );
    expect(screen.queryByText(/screen the book first/)).not.toBeInTheDocument();
    const cet4 = screen.getByTestId("book-cet4");
    expect(within(cet4).getByRole("progressbar")).toHaveAttribute("aria-valuenow", "15");
    expect(cet4).toHaveTextContent("Learning 120 · known 480 · 15% met");
    expect(within(screen.getByTestId("book-oxford3000")).queryByRole("progressbar")).toBeNull();
  });

  it("sets the daily new words, empty meaning the default", async () => {
    const chosen = overview({ book_id: "cet4", daily_new: 20 });
    api
      .mockResolvedValueOnce(chosen)
      .mockResolvedValueOnce(undefined)
      .mockResolvedValueOnce({ ...chosen, daily_new: null });
    show();
    const input = await screen.findByLabelText("New words a day");
    const save = screen.getByRole("button", { name: "Save" });
    expect(input).toHaveValue(20);
    expect(save).toBeDisabled(); // unchanged

    await userEvent.clear(input);
    await userEvent.type(input, "500");
    expect(save).toBeDisabled();
    await userEvent.clear(input);
    await userEvent.click(save);
    expect(api).toHaveBeenCalledWith("/vocab/book", {
      method: "PUT",
      json: { book_id: "cet4", daily_new: null },
    });
    await waitFor(() => expect(screen.getByLabelText("New words a day")).toHaveValue(null));
  });
});
