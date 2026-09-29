import { fireEvent, render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import type { ComponentProps } from "react";
import { describe, expect, it } from "vitest";

import type { Activity } from "@/lib/activity";

import en from "../../../messages/en.json";
import { TurnActivity } from "./turn-activity";

const step = (name: string, summary: Record<string, unknown>, extra: Partial<Activity> = {}) =>
  ({
    turn_id: "u1",
    name,
    kind: "background",
    call_id: "",
    status: "ok",
    duration_ms: 1,
    summary,
    ...extra,
  }) as Activity;

function show(props: Partial<ComponentProps<typeof TurnActivity>>) {
  return render(
    <NextIntlClientProvider locale="en" messages={en}>
      <TurnActivity activities={[]} memories={{}} kcs={{}} waiting={false} {...props} />
    </NextIntlClientProvider>,
  );
}

describe("TurnActivity", () => {
  it("shows one line, and the details when opened", () => {
    show({
      activities: [
        step("load_context", { facts: ["f1", "gone"], episodes: [], profile_items: 0 }),
        step("reflect_memory", { added: ["f2"], updated: [], deleted: 0, profile_fields: [] }),
        step("grammar_tagging", {
          mistakes: [
            {
              kc_id: "g.third",
              error_type: "omission",
              severity: "medium",
              original: "she like",
              correction: "she likes",
            },
          ],
          used_correctly: [],
        }),
      ],
      memories: {
        f1: { kind: "fact", content: "Works as a nurse." },
        f2: { kind: "fact", content: "Has a sister." },
      },
      kcs: { "g.third": { name_en: "Third person -s", name_zh: "第三人称单数", cefr: "A1" } },
    });

    const toggle = screen.getByRole("button", {
      name: "What the tutor did: read 2 memories · saved 1 · marked 1 grammar mistake",
    });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("Has a sister.")).toBeNull();

    fireEvent.click(toggle);

    expect(screen.getByText("Works as a nurse.")).toBeInTheDocument();
    expect(screen.getByText("(this memory was deleted)")).toBeInTheDocument();
    expect(screen.getByText("Has a sister.")).toBeInTheDocument();
    expect(screen.getByText("she like")).toHaveClass("line-through");
    expect(screen.getByText(/Third person -s \(A1\)/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Manage memories" })).toHaveAttribute("href", "/memory");
  });

  it("says when reflection is still running or was skipped", () => {
    const { rerender } = show({ waiting: true });
    expect(screen.getByRole("button")).toHaveTextContent("working on it…");

    rerender(
      <NextIntlClientProvider locale="en" messages={en}>
        <TurnActivity
          activities={[step("reflect_memory", {}, { status: "skipped" })]}
          memories={{}}
          kcs={{}}
          waiting={false}
        />
      </NextIntlClientProvider>,
    );
    fireEvent.click(screen.getByRole("button"));
    expect(screen.getByText(/Updating memories was skipped/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Go to Settings" })).toHaveAttribute("href", "/settings");
  });

  it("renders nothing for a turn without activity", () => {
    const { container } = show({});
    expect(container).toBeEmptyDOMElement();
  });
});
