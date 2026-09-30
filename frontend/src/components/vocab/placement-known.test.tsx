import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { PlacementKnown as Offer } from "@/lib/vocab";

import en from "../../../messages/en.json";
import { PlacementKnown } from "./placement-known";

const api = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  api,
}));

const offer = (over: Partial<Offer> = {}): Offer => ({
  unavailable: null,
  book_id: "cet4",
  up_to_rank: 1920,
  count: 0,
  marked: 0,
  ...over,
});

function show(quiet = false) {
  return render(
    <NextIntlClientProvider locale="en" messages={en}>
      <PlacementKnown quiet={quiet} />
    </NextIntlClientProvider>,
  );
}

beforeEach(() => api.mockReset());

describe("PlacementKnown", () => {
  it("marks the offered words once confirmed, then undoes the batch", async () => {
    api
      .mockResolvedValueOnce(offer({ count: 812 }))
      .mockResolvedValueOnce({ count: 812 })
      .mockResolvedValueOnce(offer({ marked: 812 }))
      .mockResolvedValueOnce({ count: 812 })
      .mockResolvedValueOnce(offer({ count: 812 }));
    show();

    await userEvent.click(await screen.findByRole("button", { name: "Mark these 812 words known" }));
    expect(api).toHaveBeenCalledWith("/vocab/placement-known", { method: "POST" });
    expect(await screen.findByTestId("placement-known-marked")).toHaveTextContent("812 words");

    await userEvent.click(screen.getByRole("button", { name: "Undo" }));
    expect(api).toHaveBeenCalledWith("/vocab/placement-known", { method: "DELETE" });
    expect(await screen.findByRole("button", { name: /Mark these 812/ })).toBeInTheDocument();
  });

  it("says why nothing is offered, with a way to choose a book", async () => {
    api.mockResolvedValueOnce(offer({ unavailable: "no_book", book_id: null }));
    show();
    expect(await screen.findByRole("link", { name: "Choose a book" })).toHaveAttribute("href", "/vocab");
  });

  it("stays out of the way when quiet and there is nothing to do", async () => {
    api.mockResolvedValueOnce(offer({ unavailable: "no_placement" }));
    const { container } = show(true);
    await vi.waitFor(() => expect(api).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });
});
