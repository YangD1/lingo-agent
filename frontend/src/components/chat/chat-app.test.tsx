import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import type { ComponentProps } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { TutorCard } from "@/lib/cards";
import type { WorkspaceDoc, WorkspaceDocDetail } from "@/lib/workspace";

import en from "../../../messages/en.json";
import { ChatApp } from "./chat-app";
import type { TutorPanel } from "./tutor-panel";

const api = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  api,
}));

// The conversation itself has its own tests: here, what the page hands it.
type PanelProps = ComponentProps<typeof TutorPanel>;
const panel = vi.hoisted(() => ({ props: null as PanelProps | null, addQuote: vi.fn() }));
vi.mock("./tutor-panel", async () => {
  const { useImperativeHandle } = await import("react");
  return {
    TutorPanel: (props: PanelProps) => {
      panel.props = props;
      useImperativeHandle(props.composerRef, () => ({ addQuote: panel.addQuote }), []);
      return <div data-testid="tutor-panel" />;
    },
  };
});

const DOC: WorkspaceDoc = {
  id: "d1",
  conversation_id: "c1",
  kind: "reading",
  title: "The fox",
  source: "paste",
  source_ref: null,
  created_by: "learner",
  version: 2,
  truncated: false,
  created_at: "2026-10-15T00:00:00Z",
  updated_at: "2026-10-15T00:00:00Z",
};
const DETAIL: WorkspaceDocDetail = {
  ...DOC,
  content: { paragraphs: ["The quick brown fox jumps.", "It runs away."] },
  words: 7,
  versions: [],
};
const OTHER: WorkspaceDoc = { ...DOC, id: "d2", kind: "writing", title: "My essay" };

function respond(docs: WorkspaceDoc[] = [DOC]) {
  api.mockImplementation((path: string, init?: { method?: string; json?: unknown }) => {
    if (path === "/conversations") return Promise.resolve([{ id: "c1", title: "Reading" }]);
    if (path === "/conversations/c1/workspace" && init?.method === "POST") {
      return Promise.resolve({ ...DETAIL, id: "d3", title: "Pasted" });
    }
    if (path === "/conversations/c1/workspace") return Promise.resolve(docs);
    if (path.startsWith("/workspace/docs/")) {
      if (init?.method === "DELETE") return Promise.resolve(undefined);
      const id = path.split("/").at(-1);
      return Promise.resolve({ ...DETAIL, ...docs.find((d) => d.id === id) });
    }
    return Promise.reject(new Error(`unexpected ${path}`));
  });
}

/** Window widths as the layout reads them (ADR 0043 §2). */
function setWidth(width: number) {
  window.matchMedia = vi.fn((query: string) => ({
    matches: width >= Number(/\d+/.exec(query)?.[0]),
    media: query,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  })) as unknown as typeof window.matchMedia;
}

function show(url: string) {
  window.history.replaceState(null, "", url);
  const params = new URLSearchParams(url.split("?")[1] ?? "");
  return render(
    <NextIntlClientProvider locale="en" messages={en} timeZone="UTC">
      <ChatApp initialId={params.get("c")} initialDocId={params.get("w")} />
    </NextIntlClientProvider>,
  );
}

const card = (kind: TutorCard["kind"], params: Record<string, unknown>): TutorCard => ({
  id: "card1",
  turn_id: "t1",
  kind,
  params,
  status: "info",
  display: {},
  created_at: null,
  decided_at: null,
  undone_at: null,
});

beforeEach(() => {
  // jsdom has no ResizeObserver; the divider's library needs one.
  globalThis.ResizeObserver ??= class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
  // Nor animations, which the conversation list's scroll area waits for.
  Element.prototype.getAnimations ??= () => [];
  setWidth(1280);
  respond();
});

afterEach(() => {
  api.mockReset();
  panel.props = null;
});

describe("ChatApp workspace (ADR 0043)", () => {
  it("opens the document in `?w=` beside the conversation, and sends with it", async () => {
    show("/chat?c=c1&w=d1");
    const pane = await screen.findByTestId("workspace");
    expect(pane).toHaveAttribute("data-layout", "split");
    expect(await within(pane).findByText("The quick brown fox jumps.")).toBeInTheDocument();
    expect(within(pane).getByTestId("workspace-version")).toHaveTextContent("Version 2");
    expect(panel.props?.workspaceDocId).toBe("d1");
    expect(screen.getByRole("separator")).toBeInTheDocument();
  });

  it("closing it keeps the conversation in the address and stops sending the document", async () => {
    show("/chat?c=c1&w=d1");
    await userEvent.click(await screen.findByRole("button", { name: "Close the workspace" }));
    expect(screen.queryByTestId("workspace")).not.toBeInTheDocument();
    expect(window.location.search).toBe("?c=c1");
    expect(panel.props?.workspaceDocId).toBeNull();
    // It can be opened again from the header.
    await userEvent.click(await screen.findByRole("button", { name: "Workspace (1)" }));
    expect(window.location.search).toBe("?c=c1&w=d1");
    expect(await screen.findByTestId("workspace")).toBeInTheDocument();
  });

  it("opens a document the tutor opened, as its card arrives (Q83b)", async () => {
    show("/chat?c=c1");
    await waitFor(() => expect(panel.props).not.toBeNull());
    expect(screen.queryByTestId("workspace")).not.toBeInTheDocument();
    respond([DOC, OTHER]);
    act(() => panel.props?.onCardShown?.(card("workspace", { doc_id: "d2", kind: "writing", title: "My essay" })));
    expect(await screen.findByTestId("workspace")).toBeInTheDocument();
    expect(window.location.search).toBe("?c=c1&w=d2");
    // Several documents: the title switches between them.
    expect(await screen.findByRole("combobox", { name: "Switch document" })).toHaveTextContent("My essay");
  });

  it("does not open anything for edits the tutor proposed: the card leads there", async () => {
    show("/chat?c=c1");
    await waitFor(() => expect(panel.props).not.toBeNull());
    act(() => panel.props?.onCardShown?.(card("workspace_edit", { doc_id: "d1", count: 2 })));
    expect(screen.queryByTestId("workspace")).not.toBeInTheDocument();
  });

  it("opens a pasted text it created, for the input box to drop it", async () => {
    show("/chat?c=c1");
    await waitFor(() => expect(panel.props).not.toBeNull());
    let opened: boolean | undefined;
    await act(async () => {
      opened = await panel.props?.openInWorkspace?.("c1", "reading", "A long text.");
    });
    expect(opened).toBe(true);
    expect(api).toHaveBeenCalledWith("/conversations/c1/workspace", {
      method: "POST",
      json: { kind: "reading", source: "paste", text: "A long text." },
    });
    expect(window.location.search).toBe("?c=c1&w=d3");
  });

  it("quotes selected text into the input box", async () => {
    show("/chat?c=c1&w=d1");
    const text = await screen.findByText("The quick brown fox jumps.");
    const range = document.createRange();
    range.selectNodeContents(text);
    // jsdom lays nothing out.
    range.getBoundingClientRect = () => new DOMRect(10, 40, 100, 20);
    window.getSelection()?.removeAllRanges();
    window.getSelection()?.addRange(range);
    fireEvent.mouseUp(text);
    await userEvent.click(await screen.findByRole("button", { name: "Ask JOJO" }));
    expect(panel.addQuote).toHaveBeenCalledWith("> The quick brown fox jumps.");
  });

  it("covers the conversation on medium screens, with a way back", async () => {
    setWidth(900);
    show("/chat?c=c1&w=d1");
    const pane = await screen.findByTestId("workspace");
    expect(pane).toHaveAttribute("data-layout", "overlay");
    expect(screen.queryByRole("separator")).not.toBeInTheDocument();
    await userEvent.click(within(pane).getByRole("button", { name: "Back to chat" }));
    expect(screen.queryByTestId("workspace")).not.toBeInTheDocument();
    expect(window.location.search).toBe("?c=c1");
  });

  it("puts chat and workspace on tabs on phones, keeping the conversation mounted", async () => {
    setWidth(400);
    show("/chat?c=c1&w=d1");
    expect(await screen.findByTestId("workspace")).toHaveAttribute("data-layout", "tabs");
    const tabs = screen.getByRole("radiogroup", { name: "Chat or workspace" });
    await userEvent.click(within(tabs).getByRole("radio", { name: "Chat" }));
    expect(screen.queryByTestId("workspace")).not.toBeInTheDocument();
    expect(screen.getByTestId("tutor-panel")).toBeVisible();
    await userEvent.click(within(tabs).getByRole("radio", { name: "Workspace" }));
    expect(await screen.findByTestId("workspace")).toBeInTheDocument();
  });

  it("closes the document when another conversation is chosen", async () => {
    show("/chat?c=c1&w=d1");
    await screen.findByTestId("workspace");
    await userEvent.click(screen.getAllByRole("button", { name: "New chat" })[0]);
    expect(screen.queryByTestId("workspace")).not.toBeInTheDocument();
  });
});
