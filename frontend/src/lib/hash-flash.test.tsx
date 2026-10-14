import { act, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { FIND_FOR_MS, FLASH_MS, flashHashTarget, useHashFlash } from "./hash-flash";

beforeEach(() => vi.useFakeTimers());
afterEach(() => {
  vi.useRealTimers();
  document.body.innerHTML = "";
  window.history.replaceState(null, "", "/");
});

function card(id: string) {
  const el = document.createElement("section");
  el.id = id;
  el.scrollIntoView = vi.fn();
  document.body.append(el);
  return el;
}

describe("flashHashTarget", () => {
  it("scrolls to the card and rings it for a while", () => {
    const el = card("usage");
    flashHashTarget("#usage");
    expect(el.scrollIntoView).toHaveBeenCalled();
    expect(el.dataset.flash).toBe("");
    vi.advanceTimersByTime(FLASH_MS);
    expect(el.dataset.flash).toBeUndefined();
  });

  it("waits for a card that renders later, and gives up on one that never does", () => {
    flashHashTarget("#connections");
    vi.advanceTimersByTime(500);
    const el = card("connections");
    vi.advanceTimersByTime(100);
    expect(el.dataset.flash).toBe("");

    flashHashTarget("#members");
    vi.advanceTimersByTime(FIND_FOR_MS + 200);
    const late = card("members");
    vi.advanceTimersByTime(200);
    expect(late.dataset.flash).toBeUndefined();
  });
});

function Page() {
  useHashFlash();
  return null;
}

describe("useHashFlash", () => {
  it("rings the card on arrival and when a link changes the hash", () => {
    const usage = card("usage");
    const routes = card("routes");
    window.history.replaceState(null, "", "/settings#usage");
    render(<Page />);
    expect(usage.dataset.flash).toBe("");

    window.history.pushState(null, "", "/settings#routes");
    act(() => {
      document.body.click();
      vi.advanceTimersByTime(1);
    });
    expect(routes.dataset.flash).toBe("");
  });
});
