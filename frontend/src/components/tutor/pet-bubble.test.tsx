import { act, fireEvent, render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import en from "../../../messages/en.json";
import { type BubbleContent, PetBubble } from "./pet-bubble";

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

const content = (extra: Partial<BubbleContent> = {}): BubbleContent => ({
  key: "ask:vocab_review",
  text: "Start your flashcards?",
  action: { href: "/vocab/review", label: "Start" },
  dismiss: "No thanks",
  lingerMs: 1000,
  ...extra,
});

function show(c: BubbleContent, onEnd = vi.fn()) {
  render(
    <NextIntlClientProvider locale="en" messages={en} timeZone="UTC">
      <PetBubble content={c} side="right" onEnd={onEnd} />
    </NextIntlClientProvider>,
  );
  return onEnd;
}

describe("PetBubble", () => {
  it("says it, with the way in and the ways out", () => {
    const onEnd = show(content());
    expect(screen.getByRole("status")).toHaveTextContent("Start your flashcards?");
    expect(screen.getByRole("link", { name: "Start" })).toHaveAttribute("href", "/vocab/review");
    fireEvent.click(screen.getByRole("button", { name: "No thanks" }));
    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(onEnd.mock.calls).toEqual([["dismiss"], ["dismiss"]]);
  });

  it("the aside does its thing and closes", () => {
    const aside = vi.fn();
    const onEnd = show(content({ aside: { label: "Ask Max instead", onClick: aside } }));
    fireEvent.click(screen.getByRole("button", { name: "Ask Max instead" }));
    expect(aside).toHaveBeenCalled();
    expect(onEnd).toHaveBeenCalledWith("dismiss");
  });

  it("goes by itself, but not while the pointer is on it", () => {
    const onEnd = show(content());
    const bubble = screen.getByTestId("pet-bubble");
    fireEvent.pointerEnter(bubble);
    act(() => vi.advanceTimersByTime(5000));
    expect(onEnd).not.toHaveBeenCalled();
    fireEvent.pointerLeave(bubble);
    act(() => vi.advanceTimersByTime(1000));
    expect(onEnd).toHaveBeenCalledWith("timeout");
  });

  it("doesn't start a drag of the pet under it", () => {
    const onPointerDown = vi.fn();
    render(
      <NextIntlClientProvider locale="en" messages={en} timeZone="UTC">
        <div onPointerDown={onPointerDown}>
          <PetBubble content={content()} side="left" onEnd={vi.fn()} />
        </div>
      </NextIntlClientProvider>,
    );
    fireEvent.pointerDown(screen.getByTestId("pet-bubble"));
    expect(onPointerDown).not.toHaveBeenCalled();
  });
});
