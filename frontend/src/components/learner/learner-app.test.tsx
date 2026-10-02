import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Evidence, KCStatus, LearnerModel } from "@/lib/learner";

import en from "../../../messages/en.json";
import { LearnerApp } from "./learner-app";

const api = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  api,
}));

const kc = (overrides: Partial<KCStatus>): KCStatus => ({
  kc_id: "g.third",
  name_en: "Third person -s",
  name_zh: "第三人称单数",
  cefr: "A1",
  p_mastery: 0.2,
  state: "weak",
  observations: 1,
  recog_correct: 0,
  produce_correct: 0,
  mistakes: 1,
  last_evidence_at: null,
  formats_passed: [],
  correct_span_hours: 0,
  last_mistake_at: null,
  mastered_at: null,
  due: null,
  ...overrides,
});

const model = (kcs: KCStatus[]): LearnerModel => ({
  kcs,
  levels: { A1: { total: 22, seen: 1 }, A2: { total: 27, seen: kcs.length - 1 } },
  skills: [],
  thresholds: { mastered: 0.95, weak: 0.4 },
  gate: { min_formats: 3, min_span_hours: 20, clean_days: 14 },
});

const MISTAKE: Evidence = {
  id: 7,
  correct: false,
  evidence: "production",
  source: "chat",
  error_type: "omission",
  severity: "low",
  original: "She like",
  correction: "She likes",
  l1_transfer: false,
  counted: false,
  conversation_id: "c1",
  conversation_title: "Music",
  created_at: "2026-09-29T10:00:00Z",
};

const TWO = model([
  kc({}),
  kc({ kc_id: "g.past", name_en: "Past simple", cefr: "A2", p_mastery: 0.6, state: "learning" }),
]);

function show(focusKc: string | null = null) {
  return render(
    <NextIntlClientProvider locale="en" messages={en} timeZone="UTC">
      <LearnerApp focusKc={focusKc} />
    </NextIntlClientProvider>,
  );
}

beforeEach(() => {
  api.mockReset();
  Element.prototype.scrollIntoView = vi.fn();
});

describe("LearnerApp", () => {
  it("guides a new learner when there is nothing yet", async () => {
    api.mockResolvedValueOnce(model([]));
    show();
    expect(await screen.findByText(/Nothing yet/)).toBeInTheDocument();
    expect(screen.getByText(/No skill estimates yet/)).toBeInTheDocument();
  });

  it("shows skills as a level and a vocabulary size, not raw ratings", async () => {
    api.mockResolvedValueOnce({
      ...model([]),
      skills: [
        { skill: "grammar", rating: 0.5, attempts: 20, cefr: "B2", vocab_size: null, reliable: null },
        { skill: "vocab", rating: 8.29, attempts: 40, cefr: "B1", vocab_size: 3100, reliable: false },
      ],
    });
    show();
    expect(await screen.findByTestId("skill-grammar")).toHaveTextContent("GrammarB220 answers");
    expect(screen.getByTestId("skill-vocab")).toHaveTextContent(
      "VocabularyB1about 3,100 words (this estimate isn't reliable)",
    );
    // Skills the placement test doesn't measure are listed too, as not assessed.
    expect(screen.getByTestId("skill-speaking")).toHaveTextContent("Not assessed");
    expect(screen.queryByText(/8\.29/)).not.toBeInTheDocument();
  });

  it("marks placement answers as such, without the stand-in error type", async () => {
    const placement: Evidence = {
      ...MISTAKE,
      source: "placement",
      evidence: "recognition",
      error_type: "wrong_choice",
      severity: "medium",
      original: null,
      correction: null,
      counted: true,
      conversation_id: null,
      conversation_title: null,
    };
    api.mockResolvedValueOnce(TWO).mockResolvedValueOnce({ evidence: [placement], total: 1 });
    show("g.third");

    const evidence = await screen.findByRole("list", { name: "Evidence" });
    expect(evidence).toHaveTextContent("Wrong in the placement test");
    expect(evidence).not.toHaveTextContent("Wrong choice");
    expect(within(evidence).getByRole("link", { name: "From the placement test" })).toHaveAttribute(
      "href",
      "/placement",
    );
  });

  it("lists grammar points with mastery in words and filters them", async () => {
    api.mockResolvedValueOnce(TWO);
    show();
    const list = await screen.findByRole("list", { name: "Grammar mastery" });
    expect(within(list).getAllByRole("listitem")).toHaveLength(2);
    expect(within(list).getByText("20% · Weak")).toBeInTheDocument();
    expect(within(list).getAllByRole("meter")[1]).toHaveAttribute("aria-valuenow", "60");
    expect(screen.getByTestId("level-coverage")).toHaveTextContent("A1 met 1/22 · A2 met 1/27");

    await userEvent.selectOptions(screen.getByLabelText("Filter by level"), "A2");
    expect(within(list).getAllByRole("listitem")).toHaveLength(1);
    await userEvent.selectOptions(screen.getByLabelText("Filter by state"), "weak");
    expect(screen.getByText("No grammar points match.")).toBeInTheDocument();
  });

  it("shows how far a point is from learned, or when a learned one is due", async () => {
    const learned = kc({
      kc_id: "g.past",
      name_en: "Past simple",
      p_mastery: 0.97,
      state: "mastered",
      formats_passed: ["choice4", "cloze", "transform"],
      correct_span_hours: 30,
      mastered_at: "2026-09-20T10:00:00Z",
      due: "2099-01-05T10:00:00Z",
    });
    const third = kc({ formats_passed: ["choice4"], correct_span_hours: 2.5 });
    api
      .mockResolvedValueOnce(model([third, learned]))
      .mockResolvedValue({ evidence: [], total: 0 });
    show("g.third");

    const progress = await screen.findByTestId("kc-learned-progress");
    const rows = within(progress).getAllByRole("listitem");
    expect(rows.map((r) => r.textContent)).toEqual([
      "Mastery 20% / 95%",
      "Question types answered right: 1 / 3",
      "Right answers spread over 2 / 20 hours",
      "No mistakes since in conversation or writing",
    ]);
    expect(rows.map((r) => r.dataset.met)).toEqual(["false", "false", "false", "true"]);

    const row = screen.getByTestId("kc-g.past");
    expect(within(row).getByText("Learned")).toBeInTheDocument();
    await userEvent.click(within(row).getByRole("button", { expanded: false }));
    expect(await within(row).findByTestId("kc-learned")).toHaveTextContent(
      "Learned on Sep 20, 2026· Next review: Jan 5, 2099",
    );
  });

  it("opens the focused point with its evidence; deleting reloads the mastery", async () => {
    api
      .mockResolvedValueOnce(TWO)
      .mockResolvedValueOnce({ evidence: [MISTAKE], total: 1 })
      .mockResolvedValueOnce(undefined)
      .mockResolvedValueOnce(model([TWO.kcs[1]]));
    show("g.third");

    const evidence = await screen.findByRole("list", { name: "Evidence" });
    expect(api).toHaveBeenCalledWith("/learner/kcs/g.third/evidence");
    expect(within(evidence).getByText("She like")).toHaveClass("line-through");
    expect(evidence).toHaveTextContent("Missing · Slip · Not counted towards mastery");
    expect(within(evidence).getByRole("link", { name: "From “Music”" })).toHaveAttribute(
      "href",
      "/chat?c=c1",
    );
    const row = within(screen.getByTestId("kc-g.third"));
    expect(row.getByRole("link", { name: "Practise with questions" })).toHaveAttribute(
      "href",
      "/practice?from=learner&kc=g.third",
    );
    expect(row.getByRole("link", { name: "Practise in conversation" })).toHaveAttribute(
      "href",
      "/chat?practice=g.third",
    );

    await userEvent.click(within(evidence).getByRole("button", { name: "Delete this record" }));
    await userEvent.click(within(evidence).getByRole("button", { name: "Delete" }));
    expect(api).toHaveBeenCalledWith("/learner/evidence/7", { method: "DELETE" });
    await waitFor(() => expect(screen.queryByTestId("kc-g.third")).not.toBeInTheDocument());
  });

  it("deletes all learning records after confirming", async () => {
    api
      .mockResolvedValueOnce(TWO)
      .mockResolvedValueOnce({ deleted: 2 })
      .mockResolvedValueOnce(model([]));
    show();
    const button = await screen.findByRole("button", { name: "Delete all learning records" });

    await userEvent.click(button);
    const dialog = await screen.findByRole("alertdialog");
    expect(dialog).toHaveTextContent("cannot be undone");
    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(api).toHaveBeenCalledTimes(1); // cancelled

    await userEvent.click(button);
    await userEvent.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Delete" }));
    expect(api).toHaveBeenCalledWith("/learner", { method: "DELETE" });
    expect(await screen.findByText(/Nothing yet/)).toBeInTheDocument();
  });
});
