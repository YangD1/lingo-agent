import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import { countWords, lengthProblem, type Submission, type SubmissionBrief } from "@/lib/writing";

import en from "../../../messages/en.json";
import { WritingApp } from "./writing-app";

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

const PROMPTS = {
  A2: [
    { id: "a2-last-weekend", en: "What did you do last weekend?", zh: "你上个周末做了什么" },
    { id: "a2-email", en: "Invite a friend to your party.", zh: "邀请朋友" },
  ],
  B1: [{ id: "b1-film", en: "Review a film you saw.", zh: "影评" }],
};

const words = (n: number) => Array.from({ length: n }, () => "word").join(" ");

const brief = (overrides: Partial<SubmissionBrief> = {}): SubmissionBrief => ({
  id: 3,
  prompt: "",
  excerpt: "Yesterday I walk to the park.",
  word_count: 26,
  status: "done",
  mistakes: 2,
  from_conversation: false,
  created_at: "2026-10-03T09:00:00Z",
  ...overrides,
});

let history: SubmissionBrief[] = [];
const submitted: unknown[] = [];

function serve({ fail }: { fail?: ApiError } = {}) {
  api.mockImplementation(async (path: string, init?: { method?: string; json?: unknown }) => {
    if (path.startsWith("/writing/prompts")) {
      const level = new URLSearchParams(path.split("?")[1]).get("level") ?? "A2";
      return { level, prompts: PROMPTS[level as keyof typeof PROMPTS] ?? [] };
    }
    if (path === "/writing" && init?.method === "POST") {
      if (fail) throw fail;
      submitted.push(init.json);
      return { id: 42 } as Submission;
    }
    if (path === "/writing") return history;
    if (path === "/writing/9") {
      return { id: 9, text: "An earlier text.", prompt: "My own task", status: "failed" };
    }
    throw new Error(`unexpected ${path}`);
  });
}

function show(again: number | null = null) {
  return render(
    <NextIntlClientProvider locale="en" messages={en}>
      <WritingApp again={again} />
    </NextIntlClientProvider>,
  );
}

beforeEach(() => {
  api.mockReset();
  push.mockReset();
  submitted.length = 0;
  history = [];
  window.localStorage.clear();
});

describe("countWords / lengthProblem", () => {
  it("counts English words as the backend does", () => {
    expect(countWords("I don't like well-known places, 你好 123.")).toBe(5);
    expect(lengthProblem(words(19))).toBe("too_short");
    expect(lengthProblem(words(20))).toBeNull();
    expect(lengthProblem(words(801))).toBe("too_long");
    expect(lengthProblem("a".repeat(6001))).toBe("too_long");
  });
});

describe("WritingApp", () => {
  it("submits a task and text, clears the draft and opens the review", async () => {
    serve();
    show();
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: /What did you do last weekend/ }));
    const box = screen.getByTestId("writing-text");
    await user.type(box, words(5));
    expect(screen.getByTestId("writing-count")).toHaveTextContent("5 English words · write at least 20");
    expect(screen.getByTestId("writing-submit")).toBeDisabled();
    expect(JSON.parse(window.localStorage.getItem("lingo.writing.draft")!)).toEqual({
      text: words(5),
      prompt: "What did you do last weekend?",
    });

    await user.type(box, ` ${words(15)}`);
    await user.click(screen.getByTestId("writing-submit"));

    await waitFor(() => expect(push).toHaveBeenCalledWith("/writing/42"));
    expect(submitted).toEqual([{ text: words(20), prompt: "What did you do last weekend?" }]);
    expect(window.localStorage.getItem("lingo.writing.draft")).toBeNull();
  });

  it("switches level, takes the learner's own task, and restores the draft", async () => {
    window.localStorage.setItem(
      "lingo.writing.draft",
      JSON.stringify({ text: "Half written.", prompt: "Describe my city" }),
    );
    serve();
    show();
    const user = userEvent.setup();

    expect(await screen.findByDisplayValue("Half written.")).toBeInTheDocument();
    // A task that isn't listed is the learner's own.
    expect(await screen.findByRole("textbox", { name: "Your task" })).toHaveValue("Describe my city");
    expect(screen.getByRole("button", { name: "My own task" })).toHaveAttribute("aria-pressed", "true");

    await user.selectOptions(screen.getByRole("combobox", { name: "Task level" }), "B1");
    expect(await screen.findByRole("button", { name: /Review a film/ })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "No task" }));
    expect(screen.queryByRole("textbox", { name: "Your task" })).not.toBeInTheDocument();
  });

  it("fills in an earlier submission to send again", async () => {
    serve();
    show(9);

    expect(await screen.findByDisplayValue("An earlier text.")).toBeInTheDocument();
    expect(await screen.findByRole("textbox", { name: "Your task" })).toHaveValue("My own task");
  });

  it("says why the backend refused the text", async () => {
    serve({ fail: new ApiError(422, "writing_too_long", "too long") });
    show();
    const user = userEvent.setup();
    await screen.findByRole("button", { name: "No task" });

    await user.type(screen.getByTestId("writing-text"), words(25));
    await user.click(screen.getByTestId("writing-submit"));

    expect(await screen.findByText(/Too long: 800 English words/)).toBeInTheDocument();
    expect(push).not.toHaveBeenCalled();
  });

  it("lists earlier writing with its status", async () => {
    history = [
      brief(),
      brief({ id: 4, status: "pending", prompt: "What did you do last weekend?" }),
      brief({ id: 5, status: "failed", from_conversation: true }),
    ];
    serve();
    show();

    const rows = await screen.findAllByTestId("writing-history");
    expect(rows).toHaveLength(3);
    expect(rows[0]).toHaveTextContent("2 grammar mistakes");
    expect(rows[0].querySelector("a")).toHaveAttribute("href", "/writing/3");
    expect(rows[1]).toHaveTextContent("What did you do last weekend?");
    expect(rows[1]).toHaveTextContent("Reviewing");
    expect(rows[2]).toHaveTextContent("from a conversation");
    expect(rows[2]).toHaveTextContent("Review failed");
  });
});
