import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import type { ComponentProps } from "react";
import { describe, expect, it, vi } from "vitest";

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
  it("tells what the tools did", () => {
    show({
      activities: [
        step("load_context", { facts: [], episodes: [], profile_items: 0, planning: true }),
        step("propose_word_book", { card_id: "k1", card_kind: "word_book" }, { kind: "tool" }),
        step("suggest_link", { card_id: null, card_kind: null }, { kind: "tool", status: "failed" }),
        step("tools", {}, { kind: "step", status: "skipped" }),
      ],
    });
    const line = screen.getByRole("button", { expanded: false });
    expect(line).toHaveTextContent("went through your placement result");
    expect(line).toHaveTextContent("showed 1 card");
    fireEvent.click(line);
    expect(screen.getByText(/Planning guidance/)).toBeInTheDocument();
    expect(screen.getByText("Showed a card: switch word book")).toBeInTheDocument();
    expect(screen.getByText(/couldn't be shown \(Page shortcut\)/)).toBeInTheDocument();
    expect(screen.getByText(/doesn't support tools/)).toBeInTheDocument();
  });

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
    expect(screen.getByRole("link", { name: "Third person -s (A1)" })).toHaveAttribute(
      "href",
      "/learner?kc=g.third",
    );
    expect(screen.getByRole("link", { name: "Learner model" })).toHaveAttribute("href", "/learner");
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

  it("says when the tutor followed a practice conversation's guidance", () => {
    show({
      activities: [
        step("load_context", {
          facts: [],
          episodes: [],
          profile_items: 0,
          practice_kc: "g.third",
        }),
      ],
      kcs: { "g.third": { name_en: "Third person -s", name_zh: "第三人称单数", cefr: "A1" } },
    });

    const line = screen.getByRole("button", { name: /^What the tutor did:/ });
    expect(line).toHaveTextContent("followed the practice plan");
    fireEvent.click(line);
    expect(screen.getByText(/^Practice guidance: Third person -s \(A1\)/)).toBeVisible();
  });

  it("renders nothing for a turn without activity", () => {
    const { container } = show({});
    expect(container).toBeEmptyDOMElement();
  });

  it("lists collected words, each removable, and those already being learned", async () => {
    const onRemoveWord = vi.fn().mockRejectedValueOnce(new Error("offline"));
    const { rerender } = show({
      activities: [
        step("vocab_collect", {
          added: [
            { word_id: 7, word: "go" },
            { word_id: 8, word: "reluctant" },
          ],
          existing: [{ word_id: 9, word: "common" }],
        }),
      ],
      wordsOnList: { 7: true, 8: false },
      onRemoveWord,
    });
    const toggle = screen.getByRole("button", {
      name: "What the tutor did: added 2 words to your word list",
    });
    fireEvent.click(toggle);

    expect(screen.getByRole("link", { name: "Word list" })).toHaveAttribute("href", "/vocab/mine");
    expect(screen.getByText("reluctant")).toHaveClass("line-through");
    expect(screen.getByText("removed")).toBeInTheDocument();
    expect(screen.getByText("Already learning: common")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Remove reluctant from your word list" })).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Remove go from your word list" }));
    expect(onRemoveWord).toHaveBeenCalledWith(7);
    expect(await screen.findByRole("alert")).toHaveTextContent("Couldn't remove it; try again");

    // Removed: the parent now reports it gone.
    rerender(
      <NextIntlClientProvider locale="en" messages={en}>
        <TurnActivity
          activities={[
            step("vocab_collect", { added: [{ word_id: 7, word: "go" }], existing: [] }),
          ]}
          memories={{}}
          kcs={{}}
          wordsOnList={{ 7: false }}
          onRemoveWord={onRemoveWord}
          waiting={false}
        />
      </NextIntlClientProvider>,
    );
    await waitFor(() => expect(screen.getByText("go")).toHaveClass("line-through"));
  });
});
