import { act, render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import en from "../../../messages/en.json";
import { CatLoading, LingoCat } from "./lingo-cat";

const wrap = (node: ReactNode) =>
  render(
    <NextIntlClientProvider locale="en" messages={en}>
      {node}
    </NextIntlClientProvider>,
  );

describe("LingoCat", () => {
  it("uses the base class for loader and a variant class for other moods", () => {
    wrap(
      <>
        <LingoCat />
        <LingoCat mood="ai" />
      </>,
    );
    const [loader, ai] = screen.getAllByRole("img");
    expect(loader).toHaveAttribute("class", expect.stringContaining("lcat"));
    expect(loader.getAttribute("class")).not.toMatch(/v-/);
    expect(ai.getAttribute("class")).toMatch(/\bv-ai\b/);
    expect(ai).toHaveAccessibleName("AI is writing");
  });

  it("switches to the small variant at 24px and below", () => {
    const { container } = wrap(
      <>
        <LingoCat size={24} />
        <LingoCat size={32} />
        <LingoCat size={64} small />
      </>,
    );
    const svgs = container.querySelectorAll("svg");
    expect(svgs[0].classList.contains("sm")).toBe(true);
    expect(svgs[1].classList.contains("sm")).toBe(false);
    expect(svgs[2].classList.contains("sm")).toBe(true);
  });

  it("hides decorative cats from assistive tech", () => {
    const { container } = wrap(
      <>
        <LingoCat mood="idle" />
        <LingoCat label="" />
      </>,
    );
    expect(screen.queryByRole("img")).toBeNull();
    container.querySelectorAll("svg").forEach((svg) => expect(svg).toHaveAttribute("aria-hidden", "true"));
  });
});

describe("CatLoading", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("announces at once but only draws the cat after 300ms", () => {
    const { container } = wrap(<CatLoading label="Loading…" />);
    expect(screen.getByRole("status")).toHaveAccessibleName("Loading…");
    expect(container.querySelector("svg")).toBeNull();
    act(() => vi.advanceTimersByTime(300));
    expect(container.querySelector("svg")).not.toBeNull();
    expect(screen.getByText("Loading…")).toBeInTheDocument();
  });
});
