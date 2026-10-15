import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { EditItem, WorkspaceDocDetail, WorkspaceEdit } from "@/lib/workspace";

import en from "../../../messages/en.json";
import { SAVE_DELAY_MS, WritingView } from "./writing-view";

const api = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  api,
}));
vi.mock("@/lib/ai-usage", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/ai-usage")>()),
  loadEstimates: () => new Promise(() => {}),
}));

const TEXT = "Yesterday I go to the park. It were sunny and I am happy.";

function docOf(text: string, version: number): WorkspaceDocDetail {
  return {
    id: "d1",
    conversation_id: "c1",
    kind: "writing",
    title: "The park",
    source: "message",
    source_ref: null,
    created_by: "learner",
    version,
    truncated: false,
    created_at: "2026-10-15T00:00:00Z",
    updated_at: "2026-10-15T00:00:00Z",
    content: { text },
    words: text.split(/\s+/).length,
    versions: Array.from({ length: version }, (_, i) => ({
      number: i + 1,
      author: i === 1 ? ("tutor" as const) : ("learner" as const),
      reverted_from: null,
      created_at: "2026-10-15T00:00:00Z",
      updated_at: "2026-10-15T00:00:00Z",
    })),
  };
}

const item = (index: number, original: string, replacement: string): EditItem => ({
  index,
  original,
  replacement,
  reason: `reason ${index}`,
  status: "pending",
  stale: false,
});

/** A fake server: the document's versions and the tutor's proposal. */
let server: { versions: string[]; edit: WorkspaceEdit };

function current() {
  return docOf(server.versions.at(-1)!, server.versions.length);
}

beforeEach(() => {
  server = {
    versions: [TEXT],
    edit: {
      id: "e1",
      doc_id: "d1",
      base_version: 1,
      created_at: "2026-10-15T00:00:00Z",
      items: [item(0, "I go to", "I went to"), item(1, "It were", "It was")],
    },
  };
  api.mockImplementation((path: string, init?: { method?: string; json?: Record<string, unknown> }) => {
    const method = init?.method ?? "GET";
    const json = init?.json ?? {};
    if (path === "/workspace/docs/d1/edits") return Promise.resolve([server.edit]);
    if (method === "PUT" && path === "/workspace/docs/d1/content") {
      server.versions.push(String(json.text));
      return Promise.resolve(current());
    }
    if (method === "POST" && path === "/workspace/edits/e1/decide") {
      let text = server.versions.at(-1)!;
      const accept = json.accept as number[];
      const decline = json.decline as number[];
      server.edit = {
        ...server.edit,
        items: server.edit.items.map((i) => {
          if (accept.includes(i.index)) {
            text = text.replace(i.original, i.replacement);
            return { ...i, status: "accepted" };
          }
          return decline.includes(i.index) ? { ...i, status: "declined" } : i;
        }),
      };
      if (accept.length) server.versions.push(text);
      return Promise.resolve({ doc: current(), edit: server.edit });
    }
    const version = path.match(/^\/workspace\/docs\/d1\/versions\/(\d+)$/);
    if (version) {
      const n = Number(version[1]);
      return Promise.resolve({ ...current().versions[n - 1], content: { text: server.versions[n - 1] } });
    }
    if (method === "POST" && path === "/workspace/docs/d1/revert") {
      server.versions.push(server.versions[Number(json.version) - 1]);
      return Promise.resolve(current());
    }
    if (method === "POST" && path === "/writing") return Promise.resolve({ id: 5, status: "pending" });
    if (path === "/writing/5") {
      return Promise.resolve({
        id: 5,
        status: "done",
        prompt: "",
        text: server.versions.at(-1),
        word_count: 13,
        summary: "Nice little story.",
        scores: null,
        corrections: [],
        words: [],
        kcs: [],
        model: null,
        error_code: null,
        from_conversation: false,
        conversation_id: null,
        created_at: "2026-10-15T00:00:00Z",
      });
    }
    return Promise.reject(new Error(`unexpected ${method} ${path}`));
  });
});

afterEach(() => {
  // Unmounting saves what is still unsaved: before the fake server goes.
  cleanup();
  api.mockReset();
  vi.useRealTimers();
});

function Harness() {
  const [doc, setDoc] = useState(current);
  return <WritingView doc={doc} onDoc={setDoc} editsSignal={0} />;
}

function show() {
  return render(
    <NextIntlClientProvider locale="en" messages={en} timeZone="UTC">
      <Harness />
    </NextIntlClientProvider>,
  );
}

const editor = () => screen.getByTestId("writing-editor") as HTMLTextAreaElement;
const calls = (method: string, path: string) =>
  api.mock.calls.filter(([p, init]) => p === path && (init?.method ?? "GET") === method);

describe("WritingView", () => {
  it("shows each proposed change word by word, with its reason", async () => {
    show();
    const items = await screen.findAllByTestId("edit-item");
    expect(items).toHaveLength(2);
    const first = items[0];
    expect(first.querySelector("del")?.textContent).toBe("go");
    expect(first.querySelector("ins")?.textContent).toBe("went");
    expect(first).toHaveTextContent("I gowent to");
    expect(first).toHaveTextContent("reason 0");
    expect(screen.getByTestId("edit-accept-all")).toBeInTheDocument();
  });

  it("accepts one change and declines another; the text is the new version", async () => {
    const user = userEvent.setup();
    show();
    const [first] = await screen.findAllByTestId("edit-item");
    await user.click(within(first).getByTestId("edit-accept"));
    await waitFor(() => expect(editor().value).toBe(TEXT.replace("I go to", "I went to")));
    expect(calls("POST", "/workspace/edits/e1/decide")[0][1].json).toEqual({ accept: [0], decline: [] });
    // The accepted one is gone; one is left, so no "accept all".
    expect(screen.getAllByTestId("edit-item")).toHaveLength(1);
    expect(screen.queryByTestId("edit-accept-all")).not.toBeInTheDocument();

    await user.click(screen.getByTestId("edit-decline"));
    await waitFor(() => expect(screen.queryByTestId("workspace-edits")).not.toBeInTheDocument());
    expect(calls("POST", "/workspace/edits/e1/decide")[1][1].json).toEqual({ accept: [], decline: [1] });
    expect(editor().value).toBe(TEXT.replace("I go to", "I went to"));
  });

  it("accepts every change at once", async () => {
    const user = userEvent.setup();
    show();
    await user.click(await screen.findByTestId("edit-accept-all"));
    await waitFor(() => expect(editor().value).toBe("Yesterday I went to the park. It was sunny and I am happy."));
    expect(calls("POST", "/workspace/edits/e1/decide")[0][1].json).toEqual({ accept: [0, 1], decline: [] });
  });

  it("marks a change whose passage the learner rewrote: it can only be declined", async () => {
    show();
    await screen.findAllByTestId("edit-item");
    fireEvent.change(editor(), { target: { value: TEXT.replace("It were", "The weather were") } });
    const [first, second] = screen.getAllByTestId("edit-item");
    expect(first).toHaveAttribute("data-stale", "false");
    expect(second).toHaveAttribute("data-stale", "true");
    expect(within(second).getByTestId("edit-accept")).toBeDisabled();
    expect(within(second).getByTestId("edit-decline")).toBeEnabled();
    expect(second).toHaveTextContent(en.chat.workspace.writing.edits.stale);
  });

  it("saves what is unsaved when the document closes", async () => {
    const view = show();
    await screen.findAllByTestId("edit-item");
    fireEvent.change(editor(), { target: { value: "Closed early." } });
    view.unmount();
    expect(calls("PUT", "/workspace/docs/d1/content")[0][1].json).toEqual({ base_version: 1, text: "Closed early." });
  });

  it("saves once typing stops, on the version it was typed on", async () => {
    vi.useFakeTimers();
    show();
    await act(() => vi.advanceTimersByTimeAsync(0));
    fireEvent.change(editor(), { target: { value: `${TEXT} The end.` } });
    expect(screen.getByTestId("writing-save-status")).toHaveTextContent(en.chat.workspace.writing.unsaved);
    await act(() => vi.advanceTimersByTimeAsync(SAVE_DELAY_MS - 100));
    expect(calls("PUT", "/workspace/docs/d1/content")).toHaveLength(0);
    await act(() => vi.advanceTimersByTimeAsync(100));
    expect(calls("PUT", "/workspace/docs/d1/content")[0][1].json).toEqual({
      base_version: 1,
      text: `${TEXT} The end.`,
    });
    expect(screen.getByTestId("writing-save-status")).toHaveTextContent(en.chat.workspace.writing.saved);
    // What was typed stays, though the server made a new version of it.
    expect(editor().value).toBe(`${TEXT} The end.`);
  });

  it("saves what was typed before deciding on a change", async () => {
    const user = userEvent.setup();
    show();
    const [first] = await screen.findAllByTestId("edit-item");
    fireEvent.change(editor(), { target: { value: `${TEXT} The end.` } });
    await user.click(within(first).getByTestId("edit-accept"));
    await waitFor(() =>
      expect(editor().value).toBe(`${TEXT.replace("I go to", "I went to")} The end.`),
    );
    const order = api.mock.calls.map(([p, init]) => `${init?.method ?? "GET"} ${p}`);
    expect(order.indexOf("PUT /workspace/docs/d1/content")).toBeLessThan(
      order.indexOf("POST /workspace/edits/e1/decide"),
    );
  });

  it("looks at an earlier version and goes back to it", async () => {
    server.versions.push("A second try.");
    const user = userEvent.setup();
    show();
    expect(editor().value).toBe("A second try.");
    await user.click(screen.getByTestId("writing-versions-toggle"));
    const versions = screen.getAllByTestId("writing-version");
    // Newest first; the current one can't be looked at or gone back to.
    expect(versions[0]).toHaveTextContent("Version 2");
    expect(versions[0]).toHaveTextContent(en.chat.workspace.writing.history.current);
    await user.click(within(versions[1]).getByRole("button", { name: en.chat.workspace.writing.history.look }));
    expect(await screen.findByTestId("writing-version-text")).toHaveTextContent(TEXT);
    await user.click(screen.getByTestId("writing-revert"));
    await waitFor(() => expect(editor().value).toBe(TEXT));
    expect(calls("POST", "/workspace/docs/d1/revert")[0][1].json).toEqual({ version: 1 });
    expect(screen.queryByTestId("writing-versions")).not.toBeInTheDocument();
  });

  it("reviews the text like /writing, once it is long enough", async () => {
    const user = userEvent.setup();
    show();
    // 13 words: too short to review.
    expect(screen.getByTestId("writing-review-button")).toBeDisabled();
    fireEvent.change(editor(), { target: { value: `${TEXT} Then we ate some ice cream and went home again.` } });
    await user.click(screen.getByTestId("writing-review-button"));
    expect(await screen.findByText("Nice little story.")).toBeInTheDocument();
    expect(calls("POST", "/writing")[0][1].json).toEqual({
      text: `${TEXT} Then we ate some ice cream and went home again.`,
      prompt: "",
    });
    // Saved first, so the review is of what the document holds.
    expect(calls("PUT", "/workspace/docs/d1/content")).toHaveLength(1);
  });
});
