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
  ...overrides,
});

const model = (kcs: KCStatus[]): LearnerModel => ({
  kcs,
  levels: { A1: { total: 22, seen: 1 }, A2: { total: 27, seen: kcs.length - 1 } },
  skills: [],
  thresholds: { mastered: 0.95, weak: 0.4 },
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
    <NextIntlClientProvider locale="en" messages={en}>
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

  it("opens the focused point with its evidence; deleting reloads the mastery", async () => {
    api
      .mockResolvedValueOnce(TWO)
      .mockResolvedValueOnce({ evidence: [MISTAKE], total: 1 })
      .mockResolvedValueOnce(undefined)
      .mockResolvedValueOnce(model([TWO.kcs[1]]));
    vi.spyOn(window, "confirm").mockReturnValue(true);
    show("g.third");

    const evidence = await screen.findByRole("list", { name: "Evidence" });
    expect(api).toHaveBeenCalledWith("/learner/kcs/g.third/evidence");
    expect(within(evidence).getByText("She like")).toHaveClass("line-through");
    expect(evidence).toHaveTextContent("Missing · Slip · Not counted towards mastery");
    expect(within(evidence).getByRole("link", { name: "From “Music”" })).toHaveAttribute(
      "href",
      "/chat?c=c1",
    );

    await userEvent.click(within(evidence).getByRole("button", { name: "Delete this record" }));
    expect(api).toHaveBeenCalledWith("/learner/evidence/7", { method: "DELETE" });
    await waitFor(() => expect(screen.queryByTestId("kc-g.third")).not.toBeInTheDocument());
  });

  it("deletes all learning records after confirming", async () => {
    api
      .mockResolvedValueOnce(TWO)
      .mockResolvedValueOnce({ deleted: 2 })
      .mockResolvedValueOnce(model([]));
    const confirm = vi.spyOn(window, "confirm").mockReturnValueOnce(false).mockReturnValue(true);
    show();
    const button = await screen.findByRole("button", { name: "Delete all learning records" });

    await userEvent.click(button);
    expect(api).toHaveBeenCalledTimes(1); // cancelled

    await userEvent.click(button);
    expect(confirm).toHaveBeenCalledTimes(2);
    expect(api).toHaveBeenCalledWith("/learner", { method: "DELETE" });
    expect(await screen.findByText(/Nothing yet/)).toBeInTheDocument();
  });
});
