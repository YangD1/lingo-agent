import { act, render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { FollowUp } from "@/lib/follow-ups";

import en from "../../../messages/en.json";
import { ReplyParts } from "./reply-parts";

function show(content: string, followUps?: FollowUp[]) {
  return render(
    <NextIntlClientProvider locale="en" messages={en}>
      <ReplyParts content={content} followUps={followUps} />
    </NextIntlClientProvider>,
  );
}

afterEach(() => vi.useRealTimers());

describe("ReplyParts", () => {
  it("is just the reply without follow-ups", () => {
    const { container } = show("Just this.");
    expect(container).toHaveTextContent("Just this.");
    expect(container.querySelector("[data-slot=follow-up]")).toBeNull();
  });

  it("puts each follow-up under its heading, saying how it ended unless done", () => {
    const { container } = show("Short.\n\nPart one.\n\nPart two.", [
      { index: 1, offset: 8, state: "ended", outcome: "done" },
      { index: 2, offset: 19, state: "ended", outcome: "timeout" },
    ]);
    const parts = container.querySelectorAll("[data-slot=follow-up]");
    expect(parts).toHaveLength(2);
    expect(parts[0]).toHaveTextContent(/^More on this\s*Part one\.$/);
    expect(parts[1]).toHaveTextContent("Part two.");
    expect(parts[1]).toHaveTextContent(en.chat.followUp.timeout);
    expect(container.firstChild).toHaveTextContent("Short.");
  });

  it("counts the seconds while a follow-up is written", () => {
    vi.useFakeTimers({ now: 10_000 });
    show("Short.", [{ index: 1, offset: null, state: "writing", startedAt: 7_000 }]);
    expect(screen.getByRole("status")).toHaveTextContent("Still thinking it through… 3 s");
    act(() => vi.advanceTimersByTime(2_000));
    expect(screen.getByRole("status")).toHaveTextContent("Still thinking it through… 5 s");
  });

  it("says a stopped follow-up was stopped", () => {
    const { container } = show("Short.", [{ index: 1, offset: null, state: "ended", outcome: "stopped" }]);
    expect(container.querySelector("[data-slot=follow-up]")).toHaveTextContent(en.chat.followUp.stopped);
    expect(screen.queryByRole("status")).toBeNull();
  });
});
