import { render, screen, within } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Dashboard, LevelSplit } from "@/lib/dashboard";

import en from "../../../messages/en.json";
import { DashboardApp } from "./dashboard-app";

const api = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  api,
}));
// Recharts needs a laid-out DOM; the charts get their own checks in E2E.
vi.mock("./book-chart", () => ({ BookChart: () => <div data-testid="book-chart" /> }));
vi.mock("./grammar-chart", () => ({ GrammarChart: () => <div data-testid="grammar-chart" /> }));
vi.mock("./skills-chart", () => ({ SkillsChart: () => <div data-testid="skills-chart" /> }));
vi.mock("./errors-chart", () => ({ ErrorsChart: () => <div data-testid="errors-chart" /> }));
// Fetches on its own; tested in advice-card.test.
vi.mock("./advice-card", () => ({ AdviceCard: () => <div data-testid="advice" /> }));

const level = (total: number, seen = 0): LevelSplit => ({
  total,
  mastered: 0,
  learning: seen,
  weak: 0,
  unseen: total - seen,
});

const days = (n: number) =>
  Array.from({ length: n }, (_, i) => ({
    date: new Date(Date.UTC(2026, 6, 9 + i)).toISOString().slice(0, 10),
    reviews: 0,
    turns: 0,
  }));

const EMPTY: Dashboard = {
  summary: {
    cefr: null,
    vocab_size: null,
    vocab_cefr: null,
    vocab_reliable: null,
    streak_days: 0,
    studied_today: false,
    reviews_due: 0,
    new_left: 0,
  },
  book: null,
  grammar: { A1: level(23), A2: level(26), B1: level(30), B2: level(20), C1: level(14), C2: level(5) },
  skills: [],
  errors: [],
  days: days(84),
};

function show() {
  return render(
    <NextIntlClientProvider locale="en" messages={en} timeZone="UTC">
      <DashboardApp />
    </NextIntlClientProvider>,
  );
}

beforeEach(() => api.mockReset());

describe("DashboardApp", () => {
  it("guides a new learner in every section instead of drawing empty charts", async () => {
    api.mockResolvedValueOnce(EMPTY);
    show();
    expect(await screen.findByTestId("stat-level")).toHaveTextContent("Not assessed");
    expect(api.mock.calls[0][0]).toMatch(/^\/dashboard(\?tz=|$)/);
    expect(screen.getByTestId("stat-streak")).toHaveTextContent("0 days");
    expect(screen.getByTestId("stat-today")).toHaveTextContent("All done for today");
    expect(within(screen.getByTestId("dashboard-book")).getByRole("link")).toHaveAttribute(
      "href",
      "/vocab",
    );
    const grammar = screen.getByTestId("dashboard-grammar");
    expect(within(grammar).getByRole("link", { name: "Chat with your tutor" })).toBeInTheDocument();
    expect(within(grammar).queryByTestId("grammar-chart")).not.toBeInTheDocument();
    expect(screen.getByTestId("dashboard-skill-listening")).toHaveTextContent("Not assessed");
    expect(screen.queryByTestId("skills-chart")).not.toBeInTheDocument();
    expect(screen.getByTestId("dashboard-errors")).toHaveTextContent(/No grammar mistakes/);
    expect(screen.getByTestId("activity-summary")).toHaveTextContent(/No study yet/);
    // The calendar is drawn even when empty: 84 days, all at the lowest shade.
    const cells = within(screen.getByTestId("dashboard-activity")).getAllByRole("listitem");
    expect(cells).toHaveLength(84);
    expect(cells.every((c) => c.dataset.level === "0")).toBe(true);
  });

  it("shows each section's numbers next to its chart", async () => {
    const recent = days(84);
    recent[83] = { ...recent[83], reviews: 6, turns: 2 };
    recent[82] = { ...recent[82], reviews: 2 };
    api.mockResolvedValueOnce({
      ...EMPTY,
      summary: {
        cefr: "B1",
        vocab_size: 3100,
        vocab_cefr: "B1",
        vocab_reliable: false,
        streak_days: 2,
        studied_today: true,
        reviews_due: 12,
        new_left: 5,
      },
      book: {
        id: "cet4",
        name_zh: "四级",
        name_en: "CET-4",
        total: 100,
        mastered: 10,
        learning: 20,
        known: 30,
        unlearned: 40,
      },
      grammar: { ...EMPTY.grammar, A2: level(26, 3) },
      skills: [
        { skill: "grammar", cefr: "B1", position: 2.5, attempts: 20, vocab_size: null, reliable: null },
        { skill: "vocab", cefr: "B1", position: 2.4, attempts: 40, vocab_size: 3100, reliable: false },
      ],
      errors: [{ kc_id: "g.third", name_en: "Third person -s", name_zh: "三单", cefr: "A1", mistakes: 3 }],
      days: recent,
    } satisfies Dashboard);
    show();

    expect(await screen.findByTestId("stat-level")).toHaveTextContent("B1");
    expect(screen.getByTestId("stat-vocab")).toHaveTextContent("About 3,100 words");
    expect(screen.getByTestId("stat-vocab")).toHaveTextContent("(rough estimate)");
    expect(screen.getByTestId("stat-streak")).toHaveTextContent("Studied today");
    expect(within(screen.getByTestId("stat-today")).getByRole("link")).toHaveTextContent(
      "5 new words left",
    );
    expect(screen.getByTestId("book-chart")).toBeInTheDocument();
    expect(screen.getByTestId("dashboard-book")).toHaveTextContent("CET-4");
    expect(screen.getByTestId("book-summary")).toHaveTextContent(
      "100 words: 10 mastered, 20 learning, 30 skipped as known, 40 not started.",
    );
    expect(screen.getByTestId("grammar-chart")).toBeInTheDocument();
    const a2 = within(screen.getByTestId("grammar-table")).getByRole("rowheader", { name: "A2" });
    expect(a2.closest("tr")).toHaveTextContent("A20302");
    expect(screen.getByTestId("skills-chart")).toBeInTheDocument();
    expect(screen.getByTestId("dashboard-skill-vocab")).toHaveTextContent(
      "About 3,100 words (reference B1)",
    );
    expect(screen.getByRole("link", { name: /Third person -s/ })).toHaveAttribute(
      "href",
      "/learner?kc=g.third",
    );
    expect(screen.getByTestId("activity-summary")).toHaveTextContent(
      "Studied 2 days in the last 12 weeks: 8 reviews, 2 chat turns.",
    );
    const cells = within(screen.getByTestId("dashboard-activity")).getAllByRole("listitem");
    expect(cells.at(-1)?.dataset.level).toBe("4");
    expect(cells.at(-2)?.dataset.level).toBe("1");
  });
});
