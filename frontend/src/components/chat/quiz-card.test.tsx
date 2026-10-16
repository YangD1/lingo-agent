import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { TutorCard } from "@/lib/cards";
import { onLessonChanged } from "@/lib/course";
import type { Item, PracticeSet } from "@/lib/practice";

import zh from "../../../messages/zh-CN.json";
import { QUIZ_POLL_MS, QuizCard, quizScore } from "./quiz-card";

const practice = vi.hoisted(() => ({
  fetchSet: vi.fn(),
  answerItem: vi.fn(),
  reportItem: vi.fn(),
}));
vi.mock("@/lib/practice", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/practice")>()),
  ...practice,
}));
vi.mock("@/lib/tutor", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/tutor")>()),
  useTutor: () => null,
}));
vi.mock("@/lib/ai-usage", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/ai-usage")>()),
  loadEstimates: () => new Promise(() => {}),
}));

const KC = { id: "g.third", name_en: "Third person -s", name_zh: "第三人称单数", cefr: "A1" as const };

const concept: Item = {
  id: 1,
  position: 0,
  kc: KC,
  format: "concept_choice",
  content: { question: "为什么是 lives？", options: ["主语是单数", "过去时", "疑问句", "都不对"] },
  status: "ok",
  from_bank: false,
  answer: null,
  result: null,
};

const explain: Item = {
  ...concept,
  id: 2,
  position: 1,
  format: "explain",
  content: { question: "什么时候动词加 -s？" },
};

const done = (item: Item, correct: boolean): Item => ({
  ...item,
  answer: { correct: "主语是单数", explanation: "第三人称单数加 -s。" },
  result: {
    correct,
    response: { choice: correct ? "主语是单数" : "过去时" },
    feedback: { explanation: "第三人称单数加 -s。", corrected: null, other_mistakes: [], model: null },
    created_at: "2026-10-15T09:00:00Z",
  },
});

const set = (overrides: Partial<PracticeSet> = {}): PracticeSet => ({
  id: "s1",
  status: "ready",
  stage: null,
  origin: "quiz",
  focus_kc: KC,
  error_code: null,
  created_at: "2026-10-15T09:00:00Z",
  started_at: "2026-10-15T09:00:00Z",
  finished_at: null,
  planned: 2,
  items: [concept, explain],
  how_made: null,
  summary: null,
  ...overrides,
});

const card = (purpose: "check" | "quiz"): TutorCard => ({
  id: "k1",
  turn_id: "u1",
  kind: "quiz",
  params: { set_id: "s1", kc_id: KC.id, purpose },
  status: "info",
  display: { kc: KC, pass_score: 0.8 },
  created_at: null,
  decided_at: null,
  undone_at: null,
});

function show(purpose: "check" | "quiz" = "check", onAsk: ((text: string) => void) | null = vi.fn()) {
  render(
    <NextIntlClientProvider locale="zh-CN" messages={zh}>
      <QuizCard card={card(purpose)} onAsk={onAsk} />
    </NextIntlClientProvider>,
  );
  return onAsk;
}

beforeEach(() => {
  practice.fetchSet.mockReset();
  practice.answerItem.mockReset();
  practice.reportItem.mockReset();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("QuizCard", () => {
  it("waits while the questions are written", async () => {
    vi.useFakeTimers();
    practice.fetchSet
      .mockResolvedValueOnce(set({ status: "generating", stage: "rewriting", items: [] }))
      .mockResolvedValueOnce(set());
    show();
    await act(async () => {});
    expect(screen.getByRole("status", { name: "有几道题没通过审题，正在重写…" })).toBeInTheDocument();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(QUIZ_POLL_MS);
    });
    expect(practice.fetchSet).toHaveBeenCalledTimes(2);
    expect(screen.getByTestId("practice-question")).toHaveTextContent("为什么是 lives？");
    expect(screen.getByText("理解检查 · 第三人称单数")).toBeInTheDocument();
  });

  it("shows each item as soon as it is written, keeping the one on show (ADR 0048)", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    // Position 1 is written first; position 0 comes in while 1 is answered.
    const writing = (items: Item[]) => set({ status: "generating", stage: "generating", items });
    practice.fetchSet
      .mockResolvedValueOnce(writing([explain]))
      .mockResolvedValueOnce(writing([concept, explain]))
      .mockResolvedValue(writing([concept, explain]));
    show();

    expect(await screen.findByTestId("practice-question")).toHaveTextContent("什么时候动词加 -s？");
    expect(screen.getByText("第 1 / 2 题")).toBeInTheDocument();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(QUIZ_POLL_MS);
    });
    // The item on show stays, though an item before it arrived.
    expect(screen.getByTestId("practice-question")).toHaveTextContent("什么时候动词加 -s？");
    expect(screen.queryByTestId("quiz-generating")).not.toBeInTheDocument();
    expect(screen.queryByTestId("quiz-summary")).not.toBeInTheDocument();
  });

  it("waits for the next item, and tells the lesson bar once the rest is stored", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    const changed = vi.fn();
    const off = onLessonChanged(changed);
    practice.fetchSet
      .mockResolvedValueOnce(set({ status: "generating", stage: "rewriting", items: [concept] }))
      .mockResolvedValueOnce(set({ status: "done", items: [done(concept, true)] }));
    practice.answerItem.mockResolvedValueOnce({ item: done(concept, true), set_done: false });
    show("quiz");

    await user.click(await screen.findByRole("button", { name: /主语是单数/ }));
    expect(screen.getByText("第 1 / 2 题")).toBeInTheDocument();
    await user.click(screen.getByTestId("practice-next"));
    expect(screen.getByRole("status", { name: "正在出下一题…" })).toBeInTheDocument();
    expect(changed).not.toHaveBeenCalled();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(QUIZ_POLL_MS);
    });
    expect(screen.getByTestId("quiz-summary")).toHaveTextContent("答对 1 / 1");
    expect(changed).toHaveBeenCalledOnce();
    off();
  });

  it("answers each item at once, then sums up and asks for a review", async () => {
    const user = userEvent.setup();
    practice.fetchSet.mockResolvedValue(set());
    practice.answerItem
      .mockResolvedValueOnce({ item: done(concept, true), set_done: false })
      .mockResolvedValueOnce({
        item: {
          ...explain,
          answer: { key_points: ["主语是 he / she / it", "一般现在时"], explanation: "" },
          result: {
            correct: false,
            response: { text: "主语是他的时候" },
            feedback: {
              explanation: "说对了一半。",
              corrected: null,
              other_mistakes: [],
              model: "fake",
              verdict: "partly",
              missing: ["一般现在时"],
            },
            created_at: "2026-10-15T09:01:00Z",
          },
        },
        set_done: true,
      });
    const onAsk = show();

    await user.click(await screen.findByRole("button", { name: /主语是单数/ }));
    expect(practice.answerItem).toHaveBeenCalledWith(1, { choice: "主语是单数" }, expect.any(Number));
    expect(screen.getByTestId("practice-verdict")).toHaveAttribute("data-correct", "true");
    await user.click(screen.getByTestId("practice-next"));

    await user.type(screen.getByLabelText("你的解释"), "主语是他的时候");
    await user.click(screen.getByRole("button", { name: "提交" }));
    expect(screen.getByText("部分正确")).toBeInTheDocument();
    expect(screen.getByTestId("practice-missing")).toHaveTextContent("一般现在时");
    expect(screen.getByText("主语是 he / she / it")).toBeInTheDocument();
    await user.click(screen.getByTestId("practice-next"));

    const summary = screen.getByTestId("quiz-summary");
    expect(summary).toHaveTextContent("理解检查完成");
    expect(summary).toHaveTextContent("答对 1 / 2");
    const ask = screen.getByRole("button", { name: "让 JOJO 讲评" });
    await user.click(ask);
    expect(onAsk).toHaveBeenCalledWith("我做完了，帮我看看。");
    expect(ask).toBeDisabled();
  });

  it("tells the lesson bar once a pass quiz is answered through", async () => {
    const user = userEvent.setup();
    const changed = vi.fn();
    const off = onLessonChanged(changed);
    practice.fetchSet.mockResolvedValue(set({ items: [concept] }));
    practice.answerItem.mockResolvedValue({ item: done(concept, true), set_done: true });
    show("quiz");
    await user.click(await screen.findByRole("button", { name: /主语是单数/ }));
    expect(changed).toHaveBeenCalledOnce();
    off();
  });

  it("does not tell the lesson bar about a check", async () => {
    const user = userEvent.setup();
    const changed = vi.fn();
    const off = onLessonChanged(changed);
    practice.fetchSet.mockResolvedValue(set({ items: [concept] }));
    practice.answerItem.mockResolvedValue({ item: done(concept, true), set_done: true });
    show("check");
    await user.click(await screen.findByRole("button", { name: /主语是单数/ }));
    expect(screen.getByTestId("practice-verdict")).toBeInTheDocument();
    expect(changed).not.toHaveBeenCalled();
    off();
  });

  it("does not take number keys from the chat", async () => {
    const user = userEvent.setup();
    practice.fetchSet.mockResolvedValue(set());
    show();
    await screen.findByTestId("practice-question");
    await user.keyboard("1");
    expect(practice.answerItem).not.toHaveBeenCalled();
  });

  it.each([
    [4, true, "测验结果 · 通过"],
    [3, false, "测验结果 · 未通过"],
  ])("a finished pass quiz with %i of 5 right shows its result", async (right, passed, text) => {
    const items = [0, 1, 2, 3, 4].map((i) => done({ ...concept, id: i + 1, position: i }, i < right));
    practice.fetchSet.mockResolvedValue(set({ status: "done", items }));
    show("quiz");
    const summary = await screen.findByTestId("quiz-summary");
    expect(summary).toHaveAttribute("data-passed", String(passed));
    expect(summary).toHaveTextContent(text);
    expect(summary).toHaveTextContent(`答对 ${right} / 5`);
  });

  it("says when no questions could be made", async () => {
    practice.fetchSet.mockResolvedValue(set({ status: "failed", items: [] }));
    show("check", null);
    expect(await screen.findByTestId("quiz-failed")).toHaveTextContent("JOJO会直接问你");
  });

  it("offers no review while a message can't be sent", async () => {
    practice.fetchSet.mockResolvedValue(set({ status: "done", items: [done(concept, true)] }));
    show("check", null);
    await screen.findByTestId("quiz-summary");
    expect(screen.queryByRole("button", { name: /讲评/ })).not.toBeInTheDocument();
  });
});

describe("quizScore", () => {
  it("counts first answers over the items not reported", () => {
    const reported: Item = { ...concept, id: 9, status: "reported" };
    expect(quizScore(set({ items: [done(concept, true), done(explain, false), reported] }))).toEqual({
      correct: 1,
      total: 2,
    });
  });
});
