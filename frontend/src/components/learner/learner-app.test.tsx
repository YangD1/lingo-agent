import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { DiagnosisPage, Evidence, KCStatus, LearnerModel } from "@/lib/learner";

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
  prerequisites: [],
  confusables: [],
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

const DIAGNOSIS: DiagnosisPage = {
  enabled: true,
  checked_at: "2026-10-07T03:45:00Z",
  diagnosis: {
    id: "d1",
    created_at: "2026-10-05T03:45:00Z",
    language: "en",
    boost_until: "2026-10-19T03:45:00Z",
    boost_active: true,
    root_causes: [
      {
        hypothesis: "You drop -s after he/she.",
        kcs: [
          { kc_id: "g.svo", name_en: "Word order", name_zh: "语序", cefr: "A1", learned: false },
          { kc_id: "g.past", name_en: "Past simple", name_zh: "一般过去时", cefr: "A2", learned: false },
        ],
        confidence: "high",
        suggestion: "Say five sentences about a friend.",
        evidence: [
          {
            id: 7,
            kc_id: "g.third",
            source: "chat",
            original: "She like",
            correction: "She likes",
            conversation_id: "c1",
            conversation_title: "Music",
            created_at: "2026-10-01T10:00:00Z",
          },
          {
            id: 8,
            kc_id: "g.third",
            source: "exercise",
            original: "He go",
            correction: "He goes",
            conversation_id: null,
            conversation_title: null,
            created_at: "2026-10-02T10:00:00Z",
          },
        ],
        cited: 3,
      },
    ],
  },
};

const NO_DIAGNOSIS: DiagnosisPage = { enabled: true, diagnosis: null, checked_at: null };

/** Answers by path, not call order: the page loads the model and the diagnosis at once.
 * A list answers its calls in turn and then keeps its last answer. */
function serve(routes: Record<string, unknown>) {
  const all: Record<string, unknown> = {
    "GET /learner/diagnosis": NO_DIAGNOSIS,
    "GET /speech/capabilities": { tts: false, tts_languages: [], shadowing: null },
    "GET /speech/shadowing?limit=20": { items: [], next_before: null },
    ...routes,
  };
  const calls: Record<string, number> = {};
  api.mockImplementation((path: string, init?: { method?: string }) => {
    const key = `${init?.method ?? "GET"} ${path}`;
    if (!(key in all)) return Promise.reject(new Error(`unexpected ${key}`));
    const answer = all[key];
    if (!Array.isArray(answer)) return Promise.resolve(answer);
    const n = calls[key] ?? 0;
    calls[key] = n + 1;
    return Promise.resolve(answer[Math.min(n, answer.length - 1)]);
  });
}

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
    serve({ "GET /learner": model([]) });
    show();
    expect(await screen.findByText(/Nothing yet/)).toBeInTheDocument();
    expect(screen.getByText(/No skill estimates yet/)).toBeInTheDocument();
  });

  it("shows skills as a level and a vocabulary size, not raw ratings", async () => {
    serve({
      "GET /learner": {
      ...model([]),
      skills: [
        { skill: "grammar", rating: 0.5, attempts: 20, cefr: "B2", vocab_size: null, reliable: null },
        { skill: "vocab", rating: 8.29, attempts: 40, cefr: "B1", vocab_size: 3100, reliable: false },
      ],
      },
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
    serve({
      "GET /learner": TWO,
      "GET /learner/kcs/g.third/evidence": { evidence: [placement], total: 1 },
    });
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
    serve({ "GET /learner": TWO });
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
    serve({
      "GET /learner": model([third, learned]),
      "GET /learner/kcs/g.third/evidence": { evidence: [], total: 0 },
      "GET /learner/kcs/g.past/evidence": { evidence: [], total: 0 },
    });
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
    serve({
      "GET /learner": [TWO, model([TWO.kcs[1]!])],
      "GET /learner/kcs/g.third/evidence": { evidence: [MISTAKE], total: 1 },
      "DELETE /learner/evidence/7": undefined,
    });
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
    serve({ "GET /learner": [TWO, model([])], "DELETE /learner": { deleted: 2 } });
    show();
    const button = await screen.findByRole("button", { name: "Delete all learning records" });

    await userEvent.click(button);
    const dialog = await screen.findByRole("alertdialog");
    expect(dialog).toHaveTextContent("cannot be undone");
    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(api).not.toHaveBeenCalledWith("/learner", { method: "DELETE" }); // cancelled

    await userEvent.click(button);
    await userEvent.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Delete" }));
    expect(api).toHaveBeenCalledWith("/learner", { method: "DELETE" });
    expect(await screen.findByText(/Nothing yet/)).toBeInTheDocument();
  });
  it("says when a diagnosis comes, or where to turn it on", async () => {
    serve({ "GET /learner": TWO });
    const { unmount } = show();
    const card = await screen.findByTestId("learner-diagnosis");
    expect(card).toHaveTextContent("once a week, and after a practice set");
    expect(within(card).queryByRole("list")).not.toBeInTheDocument();
    unmount();

    serve({ "GET /learner": TWO, "GET /learner/diagnosis": { ...NO_DIAGNOSIS, enabled: false } });
    show();
    const off = await screen.findByTestId("learner-diagnosis");
    await waitFor(() => expect(off).toHaveTextContent("Tutor's diagnosis is off"));
    expect(within(off).getByRole("link", { name: "Settings" })).toHaveAttribute(
      "href",
      "/settings#background",
    );
  });

  it("shows the diagnosis: causes, where they lie, and the mistakes they cite", async () => {
    serve({
      "GET /learner": TWO,
      "GET /learner/diagnosis": DIAGNOSIS,
      "GET /learner/kcs/g.past/evidence": { evidence: [], total: 0 },
    });
    show();
    const card = await screen.findByTestId("learner-diagnosis");
    await waitFor(() => expect(card).toHaveTextContent("You drop -s after he/she."));
    expect(card).toHaveTextContent("Diagnosed on Oct 5, 2026. Until Oct 19, 2026");
    expect(card).toHaveTextContent("Looked again on Oct 7, 2026; nothing new found.");
    expect(card).toHaveTextContent("Confidence: high");
    expect(card).toHaveTextContent("Try: Say five sentences about a friend.");
    expect(card).toHaveTextContent("1 of the 3 cited mistakes deleted");
    // Practice starts at the root of the cause.
    expect(within(card).getByRole("link", { name: "Practise with questions" })).toHaveAttribute(
      "href",
      "/practice?from=learner&kc=g.svo",
    );

    // Not in the list: a name only.
    expect(within(card).queryByRole("button", { name: /Word order/ })).not.toBeInTheDocument();
    await userEvent.click(within(card).getByRole("button", { name: /Show the 2 mistakes/ }));
    const cited = within(card).getByRole("list", { name: "Cited mistakes" });
    expect(within(cited).getByText("She like")).toHaveClass("line-through");
    expect(within(cited).getByRole("link", { name: "From “Music”" })).toHaveAttribute(
      "href",
      "/chat?c=c1",
    );
    expect(cited).toHaveTextContent("From practice");

    // Listed: opens that grammar point.
    await userEvent.click(within(card).getByRole("button", { name: /Past simple/ }));
    const row = screen.getByTestId("kc-g.past");
    expect(within(row).getByRole("button", { expanded: true })).toBeInTheDocument();
    expect(Element.prototype.scrollIntoView).toHaveBeenCalled();
  });

  it("marks an old diagnosis, and deletes one after confirming", async () => {
    const old = { ...DIAGNOSIS.diagnosis!, boost_active: false };
    serve({
      "GET /learner": TWO,
      "GET /learner/diagnosis": [{ ...DIAGNOSIS, diagnosis: old, checked_at: old.created_at }, NO_DIAGNOSIS],
      "DELETE /learner/diagnoses/d1": undefined,
    });
    show();
    const card = await screen.findByTestId("learner-diagnosis");
    await waitFor(() => expect(card).toHaveTextContent("Older diagnosis"));
    expect(card).toHaveTextContent("it no longer affects practice");
    expect(card).not.toHaveTextContent("Looked again");

    await userEvent.click(within(card).getByRole("button", { name: "This diagnosis is wrong" }));
    const dialog = await screen.findByRole("alertdialog");
    expect(dialog).toHaveTextContent("the memory it wrote will be deleted too");
    await userEvent.click(within(dialog).getByRole("button", { name: "Delete" }));
    expect(api).toHaveBeenCalledWith("/learner/diagnoses/d1", { method: "DELETE" });
    await waitFor(() => expect(card).toHaveTextContent("once a week"));
  });

  it("links a grammar point to what it builds on and what it is confused with", async () => {
    const third = kc({
      prerequisites: [{ kc_id: "g.past", name_en: "Past simple", name_zh: "一般过去时", cefr: "A2" }],
      confusables: [{ kc_id: "g.svo", name_en: "Word order", name_zh: "语序", cefr: "A1" }],
    });
    serve({
      "GET /learner": model([third, TWO.kcs[1]!]),
      "GET /learner/kcs/g.third/evidence": { evidence: [], total: 0 },
      "GET /learner/kcs/g.past/evidence": { evidence: [], total: 0 },
    });
    show("g.third");
    const row = within(await screen.findByTestId("kc-g.third"));
    expect(await row.findByText("Builds on:")).toBeInTheDocument();
    expect(row.getByText("Often confused with:")).toBeInTheDocument();
    expect(row.queryByRole("button", { name: "Word order" })).not.toBeInTheDocument();
    expect(row.getByText("Word order")).toBeInTheDocument();

    await userEvent.click(row.getByRole("button", { name: "Past simple" }));
    const past = screen.getByTestId("kc-g.past");
    expect(within(past).getByRole("button", { expanded: true })).toBeInTheDocument();
  });
});
