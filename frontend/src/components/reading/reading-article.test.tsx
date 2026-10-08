import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { formOf, pieces, type ReadingSession, type Version } from "@/lib/reading";

import en from "../../../messages/en.json";
import { POLL_MS, ReadingArticle } from "./reading-article";

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

const ARTICLE = {
  id: 7,
  feed_id: "gv",
  feed_title: "Global Voices",
  title: "A comet over the city",
  url: "https://globalvoices.org/comet",
  author: null,
  published_at: "2026-10-08T09:00:00Z",
  word_count: 640,
  summary_only: false,
  license: "cc_by",
  tags: [],
  body: "The original comet story.\n\nIt was seen by many.",
  site_url: null,
};

const version = (overrides: Partial<Version> = {}): Version => ({
  id: "v1",
  article: ARTICLE,
  level: "A2",
  status: "ready",
  stage: null,
  error_code: null,
  title: "Comet news",
  paragraphs: ["A comet is in the sky.", "People can see the comet’s light at night."],
  word_count: 16,
  glossary: [{ word: "comet", word_id: 1, form: "comet" }],
  questions: [
    { question: "Where is the comet?", options: ["In the sea", "In the sky", "At home", "Nowhere"] },
    { question: "When can people see it?", options: ["At noon", "At night", "Never", "Always"] },
  ],
  ...overrides,
});

const session = (overrides: Partial<ReadingSession> = {}): ReadingSession => ({
  id: "s1",
  article: ARTICLE,
  level: "A2",
  version: version(),
  original_reason: null,
  results: null,
  finished_at: null,
  ...overrides,
});

const calls: { path: string; method?: string; json?: unknown }[] = [];

function serve(opened: ReadingSession | (() => ReadingSession), versions: Version[] = []) {
  api.mockImplementation(async (path: string, init?: { method?: string; json?: unknown }) => {
    calls.push({ path, method: init?.method, json: init?.json });
    if (path === "/reading/articles/7/session") return typeof opened === "function" ? opened() : opened;
    if (path === "/reading/versions/v1") return versions.shift() ?? version();
    if (path === "/reading/sessions/s1/marks") return { due: [{ word_id: 2, form: "light" }] };
    if (path === "/reading/sessions/s1/marks?original=true") return { due: [{ word_id: 3, form: "seen" }] };
    if (path === "/reading/sessions/s1/answers") {
      return {
        results: [
          { choice: 1, correct: true, answer: 1, evidence: "A comet is in the sky." },
          { choice: 0, correct: false, answer: 1, evidence: "People can see the comet’s light at night." },
        ],
        counted: true,
      };
    }
    if (path === "/conversations") return { id: "c9" };
    throw new Error(`unexpected ${path}`);
  });
}

function show() {
  return render(
    <NextIntlClientProvider locale="en" messages={en} timeZone="UTC">
      <ReadingArticle id={7} />
    </NextIntlClientProvider>,
  );
}

const word = (text: string) => screen.getByTestId("reading-text").querySelector(`[data-word="${text}"]`);

beforeEach(() => {
  api.mockReset();
  push.mockReset();
  calls.length = 0;
});

afterEach(() => {
  vi.useRealTimers();
});

describe("ReadingArticle", () => {
  it("shows my version with due words and glossary words marked", async () => {
    serve(session());
    show();
    expect(await screen.findByTestId("reading-title")).toHaveTextContent("Comet news");
    expect(screen.getByTestId("reading-license")).toHaveTextContent(
      "Rewritten for your level from Global Voices; the original is CC BY 3.0.",
    );
    await waitFor(() => expect(word("light")).toHaveAttribute("data-due", "true"));
    expect(word("comet")).toHaveAttribute("data-glossary", "true");
    expect(word("comet’s")).not.toHaveAttribute("data-glossary");
    expect(screen.getByTestId("reading-legend")).toHaveTextContent("1 word due for review today");
  });

  it("switches to the original, with its own due words", async () => {
    serve(session());
    show();
    await screen.findByTestId("reading-title");
    await userEvent.click(screen.getByRole("radio", { name: "Original" }));
    expect(screen.getByTestId("reading-title")).toHaveTextContent("A comet over the city");
    expect(screen.getByTestId("reading-text")).toHaveTextContent("The original comet story.");
    await waitFor(() => expect(word("seen")).toHaveAttribute("data-due", "true"));
    expect(word("comet")).not.toHaveAttribute("data-glossary");
    expect(screen.getByTestId("reading-license")).toHaveTextContent("Original text from Global Voices.");
  });

  it("polls a version being written until it is ready", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const writing = version({ status: "generating", stage: "reviewing", paragraphs: [], title: null, questions: [] });
    serve(session({ version: writing }), [writing, version()]);
    show();
    expect(await screen.findByText("Checking the questions…")).toBeInTheDocument();
    // Meanwhile the original is there to read.
    expect(screen.getByTestId("reading-text")).toHaveTextContent("The original comet story.");
    await act(() => vi.advanceTimersByTimeAsync(POLL_MS * 2));
    expect(await screen.findByText("Comet news")).toBeInTheDocument();
    expect(screen.queryByTestId("reading-generating")).not.toBeInTheDocument();
  });

  it("offers a retry when the rewrite failed", async () => {
    let first = true;
    serve(() => {
      const opened = first
        ? session({ version: version({ status: "failed", error_code: "generation_failed" }) })
        : session();
      first = false;
      return opened;
    });
    show();
    expect(await screen.findByTestId("reading-failed")).toHaveTextContent("generation_failed");
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("Comet news")).toBeInTheDocument();
  });

  it("grades the answers and shows the evidence", async () => {
    serve(session());
    show();
    const quiz = await screen.findByTestId("reading-quiz");
    const submit = within(quiz).getByRole("button", { name: "Check my answers" });
    expect(submit).toBeDisabled();
    await userEvent.click(within(quiz).getByRole("radio", { name: "In the sky" }));
    await userEvent.click(within(quiz).getByRole("radio", { name: "At noon" }));
    await userEvent.click(submit);
    expect(await within(quiz).findByTestId("reading-score")).toHaveTextContent("1 of 2 right");
    expect(within(quiz).getByText("This counts toward your reading level.")).toBeInTheDocument();
    expect(within(quiz).getAllByText(/In the text:/)).toHaveLength(2);
    expect(calls).toContainEqual({ path: "/reading/sessions/s1/answers", method: "POST", json: { choices: [1, 0] } });
    expect(within(quiz).queryByRole("button", { name: "Check my answers" })).not.toBeInTheDocument();
  });

  it("shows earlier results when reopened", async () => {
    serve(
      session({
        results: [
          { choice: 1, correct: true, answer: 1, evidence: "A comet is in the sky." },
          { choice: 1, correct: true, answer: 1, evidence: "At night." },
        ],
      }),
    );
    show();
    expect(await screen.findByTestId("reading-score")).toHaveTextContent("2 of 2 right");
    expect(screen.getByRole("radio", { name: /In the sky/ })).toBeChecked();
  });

  it("shows a summary-only article with a link to its source and no questions", async () => {
    serve(
      session({
        article: { ...ARTICLE, summary_only: true, body: "A short teaser." },
        version: null,
        original_reason: "summary_only",
      }),
    );
    show();
    expect(await screen.findByText("This feed gives only a summary. Read the whole article at its source.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Read it at the source" })).toHaveAttribute("href", ARTICLE.url);
    expect(screen.queryByTestId("reading-quiz")).not.toBeInTheDocument();
    expect(screen.queryByTestId("reading-view")).not.toBeInTheDocument();
  });

  it("asks the tutor in a conversation about the article", async () => {
    serve(session());
    show();
    await userEvent.click(await screen.findByTestId("reading-ask"));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/chat?c=c9"));
    expect(calls).toContainEqual({
      path: "/conversations",
      method: "POST",
      json: { article_id: 7, locale: "en" },
    });
  });
});

describe("pieces", () => {
  it("cuts a paragraph into words the way the backend does", () => {
    expect(pieces("The comet’s tail — well-known!").filter((p) => p.word).map((p) => p.text)).toEqual([
      "The",
      "comet’s",
      "tail",
      "well-known",
    ]);
    expect(formOf("Comet’s")).toBe("comet's");
  });
});
