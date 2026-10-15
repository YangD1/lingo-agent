import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import type { Course, Lesson } from "@/lib/course";

import en from "../../../messages/en.json";
import { CourseApp } from "./course-app";
import { CourseEntry } from "./course-entry";

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

const lesson = (number: number, kc_id: string, cefr: Lesson["cefr"], state: Lesson["state"], extra: Partial<Lesson> = {}): Lesson => ({
  number,
  kc_id,
  name_en: `Point ${kc_id}`,
  name_zh: `语法 ${kc_id}`,
  cefr,
  state,
  p_mastery: 0.3,
  quiz_score: null,
  blocked_by: [],
  ...extra,
});

const COURSE: Course = {
  level: "A2",
  current: "g.b",
  pass_score: 0.8,
  lessons: [
    lesson(1, "g.a", "A1", "passed", { quiz_score: 0.9 }),
    lesson(2, "g.b", "A2", "available"),
    lesson(3, "g.c", "A2", "locked", { blocked_by: ["g.b"] }),
    lesson(4, "g.d", "B1", "available"),
  ],
};

function show(ui = <CourseApp />) {
  return render(
    <NextIntlClientProvider locale="en" messages={en} timeZone="UTC">
      {ui}
    </NextIntlClientProvider>,
  );
}

beforeEach(() => {
  api.mockReset();
  push.mockReset();
});

describe("CourseApp", () => {
  it("shows the current lesson and opens only its level", async () => {
    api.mockResolvedValueOnce(COURSE);
    show();
    const current = await screen.findByTestId("course-current");
    expect(current).toHaveTextContent("Continue: lesson 2 · Point g.b");
    expect(current).toHaveTextContent("1 / 4 lessons passed");
    expect(api).toHaveBeenCalledWith("/course");

    const a2 = screen.getByTestId("course-level-A2");
    expect(within(a2).getByRole("button", { name: /A2/ })).toHaveAttribute("aria-expanded", "true");
    expect(within(a2).getAllByTestId("course-lesson").map((r) => r.dataset.state)).toEqual(["available", "locked"]);
    // Other levels stay folded.
    expect(within(screen.getByTestId("course-level-A1")).queryByTestId("course-lesson")).toBeNull();
    expect(screen.queryByTestId("course-level-C2")).toBeNull();
  });

  it("names what a locked lesson waits for and offers to test out", async () => {
    api.mockResolvedValueOnce(COURSE);
    show();
    const locked = (await screen.findAllByTestId("course-lesson")).find((r) => r.dataset.kc === "g.c")!;
    expect(locked).toHaveTextContent("Locked");
    expect(locked).toHaveTextContent("Pass first: Point g.b");
    expect(within(locked).queryByRole("button", { name: "Start" })).toBeNull();

    api.mockResolvedValueOnce({ conversation: { id: "c9" }, card: {} });
    await userEvent.click(within(locked).getByRole("button", { name: "I already know this" }));
    expect(api).toHaveBeenLastCalledWith("/course/lessons/g.c/test-out", { method: "POST", json: { locale: "en" } });
    expect(push).toHaveBeenCalledWith("/chat?c=c9");
  });

  it("starts the current lesson and opens its conversation", async () => {
    api.mockResolvedValueOnce(COURSE);
    show();
    const current = await screen.findByTestId("course-current");
    api.mockResolvedValueOnce({ conversation: { id: "c1" } });
    await userEvent.click(within(current).getByRole("button", { name: "Start" }));
    expect(api).toHaveBeenLastCalledWith("/course/lessons/g.b", { method: "POST", json: { locale: "en" } });
    expect(push).toHaveBeenCalledWith("/chat?c=c1");
  });

  it("keeps the page and shows the error by the lesson when starting fails", async () => {
    api.mockResolvedValueOnce(COURSE);
    show();
    const current = await screen.findByTestId("course-current");
    api.mockRejectedValueOnce(new ApiError(409, "lesson_locked", "locked"));
    const start = within(current).getByRole("button", { name: "Start" });
    await userEvent.click(start);
    expect(await within(current).findByRole("alert")).toBeInTheDocument();
    expect(start).toBeEnabled();
    expect(push).not.toHaveBeenCalled();
  });

  it("folds and unfolds a level, and labels passed lessons for another go", async () => {
    api.mockResolvedValueOnce(COURSE);
    show();
    const a1 = await screen.findByTestId("course-level-A1");
    await userEvent.click(within(a1).getByRole("button", { name: /A1/ }));
    const row = within(a1).getByTestId("course-lesson");
    expect(row).toHaveTextContent("Passed");
    expect(row).toHaveTextContent("Last quiz 90%");
    expect(within(row).getByRole("button", { name: "Go over again" })).toBeInTheDocument();
  });

  it("says when every lesson is passed", async () => {
    api.mockResolvedValueOnce({ ...COURSE, current: null, lessons: [lesson(1, "g.a", "A1", "passed")] });
    show();
    expect(await screen.findByTestId("course-current")).toHaveTextContent("Every lesson is passed");
  });
});

describe("CourseEntry", () => {
  it("shows the current lesson and progress, linking to the course", async () => {
    api.mockResolvedValueOnce(COURSE);
    show(<CourseEntry />);
    const entry = await screen.findByTestId("course-entry");
    expect(entry).toHaveTextContent("Continue: lesson 2 · Point g.b");
    expect(entry).toHaveTextContent("1 / 4 lessons passed");
    expect(within(entry).getByRole("link", { name: "Open the course" })).toHaveAttribute("href", "/course");
  });

  it("stays hidden when the course fails to load", async () => {
    api.mockRejectedValueOnce(new Error("down"));
    const { container } = show(<CourseEntry />);
    await Promise.resolve();
    expect(container).toBeEmptyDOMElement();
  });
});
