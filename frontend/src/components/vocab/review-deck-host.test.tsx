import { fireEvent, render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import en from "../../../messages/en.json";
import { ReviewDeckHost, reviewLinkMode } from "./review-deck-host";
import type { ReviewMode } from "./use-review-session";

const params = vi.hoisted(() => ({ current: new URLSearchParams() }));
vi.mock("next/navigation", () => ({ useSearchParams: () => params.current }));
// The deck itself is covered by review-deck.test.tsx.
vi.mock("./review-deck", () => ({
  ReviewDeck: ({ mode, onClose }: { mode: string; onClose: () => void }) => (
    <button type="button" data-testid="deck" data-mode={mode} onClick={onClose}>
      deck
    </button>
  ),
}));

function link(href: string, attrs: Record<string, string> = {}) {
  const a = document.createElement("a");
  a.href = href;
  for (const [k, v] of Object.entries(attrs)) a.setAttribute(k, v);
  a.textContent = "go";
  document.body.append(a);
  return a;
}

function clickOn(target: Element, init: MouseEventInit = {}) {
  let seen: ReviewMode | null | undefined;
  const listener = (event: MouseEvent) => {
    seen = reviewLinkMode(event);
    event.preventDefault();
  };
  document.addEventListener("click", listener, { capture: true, once: true });
  fireEvent.click(target, init);
  return seen;
}

afterEach(() => {
  document.body.innerHTML = "";
  window.history.replaceState(null, "", "/");
});

describe("reviewLinkMode", () => {
  it("takes a plain click on a link to flashcards, with its mode", () => {
    expect(clickOn(link("/vocab/review"))).toBe("all");
    expect(clickOn(link("/vocab/review?mode=new"))).toBe("new");
    // Inside the link, e.g. on its icon.
    const a = link("/vocab/review");
    const icon = document.createElement("span");
    a.append(icon);
    expect(clickOn(icon)).toBe("all");
  });

  it("leaves other links, new tabs and modified clicks alone", () => {
    expect(clickOn(link("/vocab"))).toBeNull();
    expect(clickOn(link("/vocab/review/x"))).toBeNull();
    expect(clickOn(link("https://example.com/vocab/review"))).toBeNull();
    expect(clickOn(link("/vocab/review", { target: "_blank" }))).toBeNull();
    expect(clickOn(link("/vocab/review"), { ctrlKey: true })).toBeNull();
    expect(clickOn(link("/vocab/review"), { metaKey: true })).toBeNull();
    expect(clickOn(link("/vocab/review"), { button: 1 })).toBeNull();
    const span = document.createElement("span");
    document.body.append(span);
    expect(clickOn(span)).toBeNull();
  });
});

describe("ReviewDeckHost", () => {
  beforeEach(() => {
    params.current = new URLSearchParams();
    window.history.replaceState(null, "", "/chat?c=12");
  });

  function host() {
    return render(
      <NextIntlClientProvider locale="en" messages={en}>
        <ReviewDeckHost />
      </NextIntlClientProvider>,
    );
  }

  it("shows nothing without the param, and the deck with it", () => {
    const { rerender } = host();
    expect(screen.queryByTestId("deck")).not.toBeInTheDocument();
    params.current = new URLSearchParams("review=new");
    rerender(
      <NextIntlClientProvider locale="en" messages={en}>
        <ReviewDeckHost />
      </NextIntlClientProvider>,
    );
    expect(screen.getByTestId("deck")).toHaveAttribute("data-mode", "new");
  });

  it("opens a link in place, keeping the page's own params, and goes back on close", () => {
    const push = vi.spyOn(window.history, "pushState");
    const back = vi.spyOn(window.history, "back").mockImplementation(() => {});
    const { rerender } = host();
    const a = link("/vocab/review");
    expect(fireEvent.click(a)).toBe(false); // default prevented: no navigation
    expect(push).toHaveBeenCalledOnce();
    expect(String(push.mock.calls[0]![2])).toMatch(/\/chat\?c=12&review=all$/);

    params.current = new URLSearchParams("c=12&review=all");
    rerender(
      <NextIntlClientProvider locale="en" messages={en}>
        <ReviewDeckHost />
      </NextIntlClientProvider>,
    );
    fireEvent.click(screen.getByTestId("deck"));
    expect(back).toHaveBeenCalledOnce();
    push.mockRestore();
    back.mockRestore();
  });

  it("drops the param in place when opened straight from the address", () => {
    window.history.replaceState(null, "", "/vocab?review=all");
    params.current = new URLSearchParams("review=all");
    const back = vi.spyOn(window.history, "back");
    host();
    fireEvent.click(screen.getByTestId("deck"));
    expect(back).not.toHaveBeenCalled();
    expect(window.location.pathname + window.location.search).toBe("/vocab");
    back.mockRestore();
  });
});
