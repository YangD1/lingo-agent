import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { type ChatDemoCopy, ChatDemo, schedule, tokenize } from "@/components/home/landing-chat-demo";

import en from "../../../messages/en.json";

const copy = en.home.demo as unknown as ChatDemoCopy;

/** jsdom has no matchMedia; this one answers the reduced-motion query. */
function setReducedMotion(reduce: boolean) {
  vi.stubGlobal("matchMedia", () => ({
    matches: reduce,
    addEventListener: () => {},
    removeEventListener: () => {},
  }));
}

describe("tokenize", () => {
  it("streams English by word and Chinese by character, keeping the bold phrase", () => {
    expect(tokenize("One fix: <b>I went</b> today")).toEqual([
      { text: "One ", bold: false },
      { text: "fix: ", bold: false },
      { text: "I ", bold: true },
      { text: "went", bold: true },
      { text: " ", bold: false },
      { text: "today", bold: false },
    ]);
    expect(tokenize("下周练 go").map((t) => t.text)).toEqual(["下", "周", "练", " ", "go"]);
  });
});

describe("schedule", () => {
  it("runs the parts in order and holds the end before looping", () => {
    const plan = schedule(20, 10);
    expect(plan.context.done).toBeLessThan(plan.reply.start);
    expect(plan.reply.done).toBe(plan.reply.start + 20 * 55);
    expect(plan.tool.start).toBeGreaterThan(plan.reply.done);
    expect(plan.note.start).toBeGreaterThan(plan.tool.done);
    expect(plan.grammar.start).toBeGreaterThan(plan.note.done);
    expect(plan.summary).toBeGreaterThan(Math.max(plan.grammar.done, plan.memory.done));
    expect(plan.end).toBeGreaterThan(plan.summary);
  });
});

describe("ChatDemo", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("shows the finished turn at once under reduced motion, with the text for screen readers", () => {
    setReducedMotion(true);
    render(<ChatDemo copy={copy} />);
    const figure = screen.getByRole("figure", { name: copy.label });
    expect(figure).toHaveTextContent(copy.stepContextDone);
    expect(figure).toHaveTextContent(copy.stepToolDone);
    expect(figure).toHaveTextContent(copy.stepMemoryDone);
    expect(figure.querySelector("figcaption")).toHaveTextContent(copy.user);
    expect(figure.querySelector("figcaption")?.textContent).not.toContain("<b>");
  });
});
