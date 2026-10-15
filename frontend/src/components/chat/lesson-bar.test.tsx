import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { type Course, type Lesson, lessonChanged } from "@/lib/course";

import en from "../../../messages/en.json";
import { LessonBar } from "./lesson-bar";

const api = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  api,
}));
vi.mock("@/lib/ai-usage", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/ai-usage")>()),
  loadEstimates: () => new Promise(() => {}),
}));
const push = vi.hoisted(() => vi.fn());
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));

const KC = { id: "g.a", name_en: "Point a", name_zh: "语法 a", cefr: "A1" };

const lesson = (number: number, kc_id: string, state: Lesson["state"]): Lesson => ({
  number,
  kc_id,
  name_en: `Point ${kc_id.slice(2)}`,
  name_zh: "",
  cefr: "A1",
  state,
  p_mastery: 0.4,
  quiz_score: null,
  blocked_by: [],
});

const course = (a: Lesson["state"], current: string): Course => ({
  level: "A1",
  current,
  pass_score: 0.8,
  lessons: [lesson(3, "g.a", a), lesson(4, "g.b", a === "passed" ? "available" : "locked")],
});

function show(onCard = vi.fn()) {
  render(
    <NextIntlClientProvider locale="en" messages={en} timeZone="UTC">
      <LessonBar conversationId="c1" kc={KC} onCard={onCard} />
    </NextIntlClientProvider>,
  );
  return onCard;
}

beforeEach(() => {
  api.mockReset();
  push.mockReset();
});

describe("LessonBar", () => {
  it("names the lesson and its state, and offers to test out", async () => {
    api.mockResolvedValueOnce(course("learning", "g.a"));
    show();
    const bar = await screen.findByTestId("lesson-bar");
    expect(await within(bar).findByText(/Lesson 3: Point a/)).toBeInTheDocument();
    expect(bar).toHaveAttribute("data-state", "learning");
    expect(within(bar).getByRole("button", { name: "I already know this" })).toBeInTheDocument();
    expect(within(bar).queryByRole("button", { name: /Next/ })).toBeNull();
    expect(within(bar).getByRole("link", { name: "Course" })).toHaveAttribute("href", "/course");
  });

  it("puts a test-out quiz into this conversation", async () => {
    api.mockResolvedValueOnce(course("learning", "g.a"));
    const onCard = show();
    const card = { id: "q1", turn_id: "test-out-1", kind: "quiz" };
    api.mockResolvedValueOnce({ conversation: { id: "c1" }, card });
    await userEvent.click(await screen.findByRole("button", { name: "I already know this" }));
    expect(api).toHaveBeenLastCalledWith("/course/lessons/g.a/test-out", { method: "POST", json: { locale: "en" } });
    expect(onCard).toHaveBeenCalledWith(card);
    expect(push).not.toHaveBeenCalled();
  });

  it("shows the error when the quiz limit is reached", async () => {
    api.mockResolvedValueOnce(course("learning", "g.a"));
    const onCard = show();
    api.mockRejectedValueOnce(new Error("quiz_limit"));
    await userEvent.click(await screen.findByRole("button", { name: "I already know this" }));
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(onCard).not.toHaveBeenCalled();
  });

  it("reloads once a pass quiz finishes, then leads to the next lesson", async () => {
    api.mockResolvedValueOnce(course("learning", "g.a"));
    show();
    await screen.findByRole("button", { name: "I already know this" });

    api.mockResolvedValueOnce(course("passed", "g.b"));
    await act(async () => lessonChanged());
    const next = await screen.findByRole("button", { name: "Next: lesson 4" });
    expect(screen.getByTestId("lesson-bar")).toHaveAttribute("data-state", "passed");
    expect(screen.queryByRole("button", { name: "I already know this" })).toBeNull();

    api.mockResolvedValueOnce({ conversation: { id: "c2" } });
    await userEvent.click(next);
    expect(api).toHaveBeenLastCalledWith("/course/lessons/g.b", { method: "POST", json: { locale: "en" } });
    expect(push).toHaveBeenCalledWith("/chat?c=c2");
  });
});
