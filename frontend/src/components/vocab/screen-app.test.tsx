import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import type { Word } from "@/lib/vocab";

import en from "../../../messages/en.json";
import { ScreenApp } from "./screen-app";

const api = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  api,
}));

const word = (id: number, spelling: string): Word => ({
  id,
  word: spelling,
  phonetic: null,
  translation: "释义",
  definition: null,
});

function show() {
  return render(
    <NextIntlClientProvider locale="en" messages={en}>
      <ScreenApp />
    </NextIntlClientProvider>,
  );
}

beforeEach(() => api.mockReset());

describe("ScreenApp", () => {
  it("submits the ticked words and moves on to the next batch", async () => {
    api
      .mockResolvedValueOnce({ words: [word(1, "apple"), word(2, "abide"), word(3, "abyss")] })
      .mockResolvedValueOnce({ known: 1, shown: 3, skipped_ahead: false })
      .mockResolvedValueOnce({ words: [word(4, "zeal")] });
    show();

    const apple = await screen.findByRole("button", { name: "apple" });
    await userEvent.click(apple);
    await userEvent.click(screen.getByRole("button", { name: "abide" }));
    await userEvent.click(screen.getByRole("button", { name: "abide" })); // untick
    expect(apple).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByTestId("screen-count")).toHaveTextContent("1 of 3 marked known");

    await userEvent.click(screen.getByRole("button", { name: "Done, next" }));
    expect(api).toHaveBeenCalledWith("/vocab/screen", {
      method: "POST",
      json: { shown: [1, 2, 3], known: [1] },
    });
    expect(await screen.findByTestId("screen-result")).toHaveTextContent("You knew 1 of 3.");

    await userEvent.click(screen.getByRole("button", { name: "Next batch" }));
    expect(await screen.findByRole("button", { name: "zeal" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
  });

  it("says so when most were known and the next batch skips ahead", async () => {
    api
      .mockResolvedValueOnce({ words: [word(1, "apple")] })
      .mockResolvedValueOnce({ known: 1, shown: 1, skipped_ahead: true });
    show();
    await userEvent.click(await screen.findByRole("button", { name: "apple" }));
    await userEvent.click(screen.getByRole("button", { name: "Done, next" }));
    expect(await screen.findByTestId("screen-result")).toHaveTextContent(/skips ahead/);
  });

  it("sends a learner without a book back, and says when the book is done", async () => {
    api.mockRejectedValueOnce(new ApiError(409, "no_book", "choose a word book first"));
    const { unmount } = show();
    expect(await screen.findByText("Choose a word book first.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to vocabulary" })).toHaveAttribute(
      "href",
      "/vocab",
    );
    unmount();

    api.mockResolvedValueOnce({ words: [] });
    show();
    expect(await screen.findByText(/every word in this book/)).toBeInTheDocument();
  });
});
