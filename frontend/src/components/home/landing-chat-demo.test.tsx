import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { type ChatDemoCopy, type ChatDemoScene, ChatDemo, schedule, tokenize } from "@/components/home/landing-chat-demo";

import en from "../../../messages/en.json";

const copy: ChatDemoCopy = {
  ...en.home.demo,
  scenes: Object.values(en.home.demo.scenes).map((scene) => ({
    ...scene,
    tool: { ...scene.tool, icon: scene.tool.icon as ChatDemoScene["tool"]["icon"] },
    after: Object.values(scene.after),
  })),
};

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
    const plan = schedule(20, 10, 2);
    expect(plan.context.done).toBeLessThan(plan.reply.start);
    expect(plan.reply.done).toBe(plan.reply.start + 20 * 45);
    expect(plan.tool.start).toBeGreaterThan(plan.reply.done);
    expect(plan.note.start).toBeGreaterThan(plan.tool.done);
    expect(plan.after[0]?.start).toBeGreaterThan(plan.note.done);
    expect(plan.after[1]?.done).toBeGreaterThan(plan.after[0]?.done ?? 0);
    expect(plan.summary).toBeGreaterThan(plan.after[1]?.done ?? 0);
    expect(plan.end).toBeGreaterThan(plan.summary);
  });
});

describe("ChatDemo", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("shows a finished turn at once under reduced motion, and the tabs switch topics", async () => {
    setReducedMotion(true);
    render(<ChatDemo copy={copy} />);
    const figure = screen.getByRole("figure", { name: copy.label });
    const [first, second] = copy.scenes;
    if (!first || !second) throw new Error("needs two topics");
    expect(figure).toHaveTextContent(first.contextDone);
    expect(figure).toHaveTextContent(first.tool.done);
    expect(figure.querySelector("figcaption")).toHaveTextContent(first.user);
    expect(figure.querySelector("figcaption")?.textContent).not.toContain("<b>");

    await userEvent.click(screen.getByRole("button", { name: second.topic }));
    expect(screen.getByRole("button", { name: second.topic })).toHaveAttribute("aria-pressed", "true");
    expect(figure.querySelector("figcaption")).toHaveTextContent(second.user);
  });
});
