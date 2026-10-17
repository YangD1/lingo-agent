"use client";

import { LayoutGridIcon, Menu, PanelRight } from "lucide-react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { useCallback, useEffect, useRef, useState } from "react";
import { Group, Panel, Separator, useDefaultLayout, usePanelRef } from "react-resizable-panels";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Segmented } from "@/components/ui/segmented";
import { Sheet } from "@/components/ui/sheet";
import { useWorkspace } from "@/components/workspace/use-workspace";
import { WorkspaceOpenerContext } from "@/components/workspace/opener";
import { WorkspacePane } from "@/components/workspace/workspace-pane";
import { type ApiErrorLike, useErrorMessage } from "@/i18n/errors";
import { api, ApiError } from "@/lib/api";
import type { TutorCard } from "@/lib/cards";
import { lessonChanged } from "@/lib/course";
import type { Conversation } from "@/lib/types";
import { cn } from "@/lib/utils";
import {
  chatUrl,
  createFrom,
  createPasted,
  deleteDoc,
  docFrom,
  listDocs,
  type DocSource,
  quoteBlock,
  useWorkspaceLayout,
  type WorkspaceKind,
} from "@/lib/workspace";

import { ConversationList } from "./conversation-list";
import { PlacementBanner } from "./placement-banner";
import { ConversationOpenerContext } from "./conversation-opener";
import { LessonBar } from "./lesson-bar";
import { PracticeBar } from "./practice-bar";
import type { ComposerHandle } from "./composer";
import { ReadingBar } from "./reading-bar";
import { TutorPanel } from "./tutor-panel";

// The active conversation lives in `?c=<id>` and the workspace document beside it in
// `&w=<id>` (ADR 0043 §2), updated with the History API so that creating a conversation
// mid-send doesn't remount the page and cut the stream.
function setUrl(id: string | null, mode: "push" | "replace" = "push") {
  const url = chatUrl(id, null);
  if (mode === "push") window.history.pushState(null, "", url);
  else window.history.replaceState(null, "", url);
}

/** Opening or closing a document stays in the same history entry as its conversation. */
function setDocUrl(docId: string | null) {
  const conversation = new URLSearchParams(window.location.search).get("c");
  window.history.replaceState(null, "", chatUrl(conversation, docId));
}

const searchParam = (name: string) =>
  typeof window === "undefined" ? null : new URLSearchParams(window.location.search).get(name);

// The divider's place is a preference of this browser only: storage may be unavailable.
const layoutStorage = {
  getItem(key: string) {
    try {
      return window.localStorage.getItem(key);
    } catch {
      return null;
    }
  },
  setItem(key: string, value: string) {
    try {
      window.localStorage.setItem(key, value);
    } catch {
      // Not kept; the default applies next time.
    }
  },
};

export function ChatApp({
  initialId,
  initialDocId = null,
  practiceKc = null,
  planning = false,
}: {
  initialId: string | null;
  /** `?w=<id>`: the workspace document open beside the conversation. */
  initialDocId?: string | null;
  /** `?practice=<kc>`: start, or return to, a practice conversation on that grammar point. */
  practiceKc?: string | null;
  /** `?plan=1`: start, or return to, an empty study-planning conversation (ADR 0015 §6). */
  planning?: boolean;
}) {
  const locale = useLocale();
  const t = useTranslations("chat");
  const tNav = useTranslations("nav");
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  // Coming back (browser Back) to a page opened with `?practice=` or `?plan=`, Next may
  // render the props it cached for that URL, though `setUrl` has since replaced it with
  // the conversation made from it: the address bar is the truth.
  const [urlId] = useState(() => searchParam("c"));
  const [activeId, setActiveId] = useState<string | null>(urlId ?? initialId);
  const [docId, setDocId] = useState<string | null>(() =>
    urlId ? searchParam("w") : initialId ? initialDocId : null,
  );
  // The conversation made from `?practice=` or `?plan=`, in case the list loads without it.
  const [practice, setPractice] = useState<Conversation | null>(null);
  const [practiceError, setPracticeError] = useState<ApiErrorLike | null>(null);

  const refresh = useCallback(() => {
    api<Conversation[]>("/conversations").then(setConversations, () => {});
  }, []);
  useEffect(refresh, [refresh]);

  // Once per point and page load (StrictMode runs effects twice). Coming back to the same
  // point returns its unstarted practice conversation instead of a new one (Q19c); an
  // empty planning conversation is returned likewise.
  const practiceStarted = useRef<string | null>(null);
  const purpose = planning ? "planning" : practiceKc ? `practice:${practiceKc}` : null;
  useEffect(() => {
    if (!purpose || urlId || practiceStarted.current === purpose) return;
    practiceStarted.current = purpose;
    api<Conversation>("/conversations", {
      method: "POST",
      json: planning ? { purpose: "planning", locale } : { focus_kc_id: practiceKc, locale },
    }).then(
      (c) => {
        setPractice(c);
        setConversations((all) => [c, ...all.filter((o) => o.id !== c.id)]);
        setActiveId(c.id);
        setUrl(c.id, "replace");
      },
      (e: unknown) =>
        setPracticeError(e instanceof ApiError ? e : { code: "network_error", message: "" }),
    );
  }, [purpose, urlId, planning, practiceKc, locale]);

  useEffect(() => {
    const onPop = () => {
      setActiveId(searchParam("c"));
      setDocId(searchParam("w"));
    };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  const active =
    conversations.find((c) => c.id === activeId) ??
    (practice?.id === activeId ? practice : undefined);

  const select = (id: string | null) => {
    setActiveId(id);
    setDocId(null); // documents belong to their conversation
    setUrl(id);
  };
  // A conversation made elsewhere on the page (a lesson card, the next lesson).
  const openConversation = (c: Conversation) => {
    setConversations((all) => [c, ...all.filter((o) => o.id !== c.id)]);
    select(c.id);
  };

  // The workspace (ADR 0043): the document open beside the chat, and how it sits there.
  const layout = useWorkspaceLayout();
  const workspace = useWorkspace(activeId, docId);
  const errorMessage = useErrorMessage();
  const [tab, setTab] = useState<"chat" | "workspace">("workspace");
  const [fullscreen, setFullscreen] = useState(false);
  const chatPanel = usePanelRef();
  const composer = useRef<ComposerHandle>(null);
  const isOpen = docId !== null;
  const split = isOpen && layout === "split";
  const panels = useDefaultLayout({
    id: "lingo.chatWorkspace",
    panelIds: split ? ["chat-column", "workspace-column"] : ["chat-column"],
    storage: layoutStorage,
    onlySaveAfterUserInteractions: true,
  });

  const openDoc = useCallback((id: string) => {
    setDocId(id);
    setTab("workspace");
    setDocUrl(id);
  }, []);
  const closeDoc = useCallback(() => {
    setDocId(null);
    setFullscreen(false);
    setDocUrl(null);
  }, []);
  const showFullscreen = (on: boolean) => {
    setFullscreen(on);
    if (on) chatPanel.current?.collapse();
    else chatPanel.current?.expand();
  };

  // The tutor opened a document (Q83b): it opens beside the chat straight away.
  // Changes it proposed are listed again in the writing view. It closed the workspace at the
  // learner's word (ADR 0045 §2): only a card arriving now closes it, not one in the history.
  const reloadDocs = workspace.reload;
  const [editsSignal, setEditsSignal] = useState(0);
  const onCardShown = useCallback(
    (card: TutorCard) => {
      if (card.status === "withdrawn") return; // taken back: nothing to open or close
      if (card.kind === "workspace_closed") return closeDoc();
      if (card.kind !== "workspace" && card.kind !== "workspace_edit") return;
      reloadDocs();
      if (card.kind === "workspace") openDoc(String(card.params.doc_id));
      else setEditsSignal((n) => n + 1);
    },
    [reloadDocs, openDoc, closeDoc],
  );

  async function openPasted(conversationId: string, kind: WorkspaceKind, text: string) {
    try {
      const doc = await createPasted(conversationId, kind, text);
      reloadDocs();
      openDoc(doc.id);
      return true;
    } catch (e) {
      toast.error(errorMessage(e instanceof ApiError ? e : { code: "network_error", message: "" }));
      return false;
    }
  }

  // The reading bar's article and writing_coach's reviewed text (ADR 0043 §3–4): opened
  // again if this conversation already has it. The list is asked for afresh: the loaded one
  // may not have arrived yet, and a stale one would make the document twice.
  async function openFrom(from: DocSource) {
    if (!activeId) return;
    const docs = await listDocs(activeId).catch(() => workspace.docs);
    const made = docFrom(docs, from);
    if (made) return openDoc(made.id);
    try {
      const doc = await createFrom(activeId, from);
      reloadDocs();
      openDoc(doc.id);
    } catch (e) {
      toast.error(errorMessage(e instanceof ApiError ? e : { code: "network_error", message: "" }));
    }
  }

  async function removeDoc() {
    if (!docId) return;
    await deleteDoc(docId).catch(() => {});
    closeDoc();
    reloadDocs();
  }

  const ask = (text: string) => {
    if (layout === "tabs") setTab("chat");
    composer.current?.addQuote(quoteBlock(text));
  };

  async function remove(id: string) {
    await api(`/conversations/${id}`, { method: "DELETE" }).catch(() => {});
    setConversations((all) => all.filter((c) => c.id !== id));
    if (id === activeId) select(null);
  }

  const list = {
    conversations,
    activeId,
    onDelete: remove,
  };

  const latestDoc = workspace.docs.at(-1);
  const pane = docId && (
    <WorkspacePane
      layout={layout}
      docs={workspace.docs}
      docId={docId}
      doc={workspace.doc}
      error={workspace.error}
      fullscreen={fullscreen}
      onFullscreen={showFullscreen}
      onSwitch={openDoc}
      onClose={closeDoc}
      onDelete={() => void removeDoc()}
      onAsk={ask}
      onDoc={workspace.replace}
      editsSignal={editsSignal}
      className="h-full"
    />
  );
  const tabs = isOpen && layout === "tabs";

  return (
    <ConversationOpenerContext value={openConversation}>
      <WorkspaceOpenerContext value={{ open: openDoc, openFrom }}>
        <ConversationList
          {...list}
          className={cn("hidden md:flex", isOpen && "md:hidden")}
          onSelect={select}
          onNew={() => select(null)}
        />
        <div className="relative flex min-w-0 flex-1 flex-col">
          {tabs && (
            <div className="flex shrink-0 items-center justify-center border-b px-3 py-2">
              <Segmented
                label={t("workspace.tabs")}
                value={tab}
                onChange={setTab}
                className="w-full max-w-xs [&>*]:flex-1"
                options={[
                  { value: "chat", label: t("workspace.tabChat") },
                  { value: "workspace", label: t("workspace.tabWorkspace") },
                ]}
              />
            </div>
          )}
          {/* One tree whatever the layout, so the conversation (and a reply streaming into
              it) stays mounted while the workspace opens, closes or changes layout. The group
              sets its own inline display, so the phone tab hides a wrapper around it. */}
          <div className={cn("flex min-h-0 flex-1 flex-col", tabs && tab === "workspace" && "hidden")}>
            <Group
              id="chat-workspace"
              className="min-h-0 flex-1"
              defaultLayout={panels.defaultLayout}
              onLayoutChanged={panels.onLayoutChanged}
            >
              <Panel
                id="chat-column"
                panelRef={chatPanel}
                minSize={split ? 360 : undefined}
                defaultSize={split ? 420 : undefined}
                collapsible={split}
                collapsedSize={0}
                onResize={(size) => split && setFullscreen(size.inPixels === 0)}
                className="flex min-w-0 flex-col"
              >
                <header className="flex h-14 shrink-0 items-center gap-1.5 border-b px-2 md:h-12 md:px-5">
                  <Button
                    variant="ghost"
                    size="icon"
                    className={cn("md:hidden", isOpen && "md:inline-flex")}
                    aria-label={t("openConversations")}
                    aria-haspopup="dialog"
                    onClick={() => setDrawerOpen(true)}
                  >
                    <Menu className="size-5" />
                  </Button>
                  <h1 className="truncate text-base font-semibold md:text-[15px]">
                    {active ? active.title || t("untitled") : t("newChat")}
                  </h1>
                  {!isOpen && latestDoc && (
                    <Button
                      variant="ghost"
                      size="sm"
                      className="ml-auto shrink-0 text-muted-foreground"
                      onClick={() => openDoc(latestDoc.id)}
                    >
                      <PanelRight />
                      {t("workspace.open", { n: workspace.docs.length })}
                    </Button>
                  )}
                </header>
                <TutorPanel
                  className="min-h-0 flex-1"
                  conversationId={activeId}
                  onConversationCreated={(c) => {
                    setActiveId(c.id);
                    setUrl(c.id, "replace");
                    setConversations((all) => [c, ...all.filter((o) => o.id !== c.id)]);
                  }}
                  onTurnFinished={() => {
                    refresh();
                    // The turn may have moved the lesson's mastery.
                    if (active?.purpose === "lesson") lessonChanged();
                  }}
                  // A practice or planning conversation with nothing in it yet (Q19a, ADR 0015 §6).
                  autoOpen={Boolean(active?.focus_kc || active?.purpose === "planning")}
                  header={({ addCard }) =>
                    active?.purpose === "lesson" && active.focus_kc ? (
                      <LessonBar conversationId={active.id} kc={active.focus_kc} onCard={addCard} />
                    ) : active?.focus_kc ? (
                      <PracticeBar kc={active.focus_kc} />
                    ) : active?.article_id ? (
                      <ReadingBar articleId={active.article_id} />
                    ) : (
                      <PlacementBanner />
                    )
                  }
                  sendFeature={active?.article_id ? "reading_coach" : undefined}
                  error={practiceError}
                  onCardShown={onCardShown}
                  workspaceDocId={docId}
                  openInWorkspace={openPasted}
                  composerRef={composer}
                />
              </Panel>
              {split && (
                <>
                  <Separator
                    className="w-px bg-border outline-none transition-colors hover:bg-ring data-[separator=active]:bg-ring focus-visible:bg-ring"
                    aria-label={t("workspace.resize")}
                  />
                  <Panel id="workspace-column" minSize={480} className="flex min-w-0 flex-col">
                    {pane}
                  </Panel>
                </>
              )}
            </Group>
          </div>
          {isOpen && layout === "overlay" && <div className="absolute inset-0 z-20 flex flex-col">{pane}</div>}
          {tabs && tab === "workspace" && <div className="flex min-h-0 flex-1 flex-col">{pane}</div>}
        </div>
        {/* Phones: the list is a drawer, and the way back to the other pages (no tab bar here). */}
        <Sheet
          side="left"
          open={drawerOpen}
          onOpenChange={setDrawerOpen}
          title={t("conversations")}
          hideTitle
          className="bg-[color-mix(in_oklab,var(--sidebar)_60%,var(--background))]"
        >
          <ConversationList
            {...list}
            className="min-h-0 w-full flex-1 border-r-0 bg-transparent"
            onSelect={(id) => {
              setDrawerOpen(false);
              select(id);
            }}
            onNew={() => {
              setDrawerOpen(false);
              select(null);
            }}
          />
          <Link
            href="/dashboard"
            className="flex h-12 shrink-0 items-center gap-2.5 border-t px-5 text-sm text-muted-foreground hover:text-foreground"
          >
            <LayoutGridIcon aria-hidden className="size-[18px]" />
            {tNav("dashboard")}
          </Link>
        </Sheet>
      </WorkspaceOpenerContext>
    </ConversationOpenerContext>
  );
}
