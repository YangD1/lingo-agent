import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import { type ArticleItem, type Feed, ownCount } from "@/lib/reading";

import en from "../../../messages/en.json";
import { ReadingList } from "./reading-list";

const api = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  api,
}));
vi.mock("@/lib/ai-usage", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/ai-usage")>()),
  loadEstimates: () => new Promise(() => {}),
}));

const feed = (overrides: Partial<Feed>): Feed => ({
  id: "nasa",
  title: "NASA",
  url: "https://www.nasa.gov/feed/",
  site_url: null,
  builtin: true,
  license: "public_domain",
  subscribed: true,
  can_delete: false,
  last_fetched_at: null,
  last_error: null,
  ...overrides,
});

const article = (id: number, overrides: Partial<ArticleItem> = {}): ArticleItem => ({
  id,
  feed_id: "nasa",
  feed_title: "NASA",
  title: `Article ${id}`,
  url: `https://example.com/${id}`,
  author: null,
  published_at: "2026-10-08T09:00:00Z",
  word_count: 640,
  summary_only: false,
  license: "public_domain",
  tags: [],
  rewritten: false,
  read: false,
  ...overrides,
});

let feeds: Feed[] = [];
const calls: { path: string; method?: string; json?: unknown }[] = [];

function serve({ addError }: { addError?: ApiError } = {}) {
  api.mockImplementation(async (path: string, init?: { method?: string; json?: unknown }) => {
    calls.push({ path, method: init?.method, json: init?.json });
    if (path === "/reading/feeds" && init?.method === "POST") {
      if (addError) throw addError;
      feeds = [...feeds, feed({ id: "mine", title: "My blog", builtin: false, license: "unknown", can_delete: true })];
      return { feeds, max_own: 5 };
    }
    if (path === "/reading/feeds") return { feeds, max_own: 5 };
    const subscription = /^\/reading\/feeds\/(\w+)\/subscription$/.exec(path);
    if (subscription) {
      const on = (init?.json as { subscribed: boolean }).subscribed;
      feeds = feeds.map((f) => (f.id === subscription[1] ? { ...f, subscribed: on } : f));
      return { feeds, max_own: 5 };
    }
    if (path.startsWith("/reading/articles?")) {
      const params = new URLSearchParams(path.split("?")[1]);
      if (params.get("before")) return { articles: [article(3)], next_cursor: null };
      if (params.get("feed_id") === "gv") {
        return { articles: [article(9, { feed_id: "gv", feed_title: "Global Voices" })], next_cursor: null };
      }
      return {
        articles: [article(1, { rewritten: true, read: true }), article(2, { summary_only: true })],
        next_cursor: "c1",
      };
    }
    throw new Error(`unexpected ${path}`);
  });
}

function show() {
  return render(
    <NextIntlClientProvider locale="en" messages={en} timeZone="UTC">
      <ReadingList />
    </NextIntlClientProvider>,
  );
}

beforeEach(() => {
  api.mockReset();
  calls.length = 0;
  feeds = [feed({}), feed({ id: "gv", title: "Global Voices", license: "cc_by" })];
});

describe("ReadingList", () => {
  it("lists articles with their marks and loads more", async () => {
    serve();
    show();
    const rows = await screen.findAllByTestId("reading-article");
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveAttribute("href", "/reading/1");
    expect(rows[0]).toHaveTextContent("Rewritten for you");
    expect(rows[0]).toHaveTextContent("Read");
    expect(rows[0]).toHaveTextContent("640 words");
    expect(rows[1]).toHaveTextContent("Summary only");
    expect(rows[1]).not.toHaveTextContent("640 words");

    await userEvent.click(screen.getByRole("button", { name: "Show more" }));
    expect(await screen.findByText("Article 3")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Show more" })).not.toBeInTheDocument();
  });

  it("filters by feed", async () => {
    serve();
    show();
    await screen.findByText("Article 1");
    const chips = screen.getByRole("group", { name: "Filter by feed" });
    await userEvent.click(within(chips).getByRole("button", { name: "Global Voices" }));
    expect(await screen.findByText("Article 9")).toBeInTheDocument();
    expect(screen.queryByText("Article 1")).not.toBeInTheDocument();
    expect(within(chips).getByRole("button", { name: "Global Voices" })).toHaveAttribute("aria-pressed", "true");
  });

  it("says so when no feed is followed", async () => {
    feeds = feeds.map((f) => ({ ...f, subscribed: false }));
    serve();
    api.mockImplementationOnce(async () => ({ feeds, max_own: 5 }));
    api.mockImplementationOnce(async () => ({ articles: [], next_cursor: null }));
    show();
    expect(await screen.findByText("You follow no feeds")).toBeInTheDocument();
  });

  it("turns feeds off and adds one in the sheet", async () => {
    serve();
    show();
    await screen.findByText("Article 1");
    await userEvent.click(screen.getByTestId("manage-feeds"));
    const sheet = await screen.findByTestId("feeds-sheet");
    expect(within(sheet).getByText("CC BY: rewritten for your level, with credit")).toBeInTheDocument();

    await userEvent.click(within(sheet).getByRole("switch", { name: "Follow Global Voices" }));
    await waitFor(() =>
      expect(calls).toContainEqual({
        path: "/reading/feeds/gv/subscription",
        method: "PUT",
        json: { subscribed: false },
      }),
    );

    await userEvent.type(within(sheet).getByTestId("feed-url"), "https://example.com/rss");
    await userEvent.click(within(sheet).getByRole("button", { name: "Add" }));
    expect(await within(sheet).findByText("My blog")).toBeInTheDocument();
    expect(within(sheet).getByText("Feeds you added", { exact: false })).toHaveTextContent("1 of 5");
    expect(within(sheet).getByRole("button", { name: "Delete My blog" })).toBeInTheDocument();
  });

  it("shows why a feed could not be added", async () => {
    serve({ addError: new ApiError(422, "feed_unreachable", "could not read a feed there: not_a_feed") });
    show();
    await screen.findByText("Article 1");
    await userEvent.click(screen.getByTestId("manage-feeds"));
    const sheet = await screen.findByTestId("feeds-sheet");
    await userEvent.type(within(sheet).getByTestId("feed-url"), "https://example.com/page");
    await userEvent.click(within(sheet).getByRole("button", { name: "Add" }));
    expect(await within(sheet).findByText(/No feed could be read at that address\. \(not_a_feed\)/)).toBeInTheDocument();
  });
});

describe("ownCount", () => {
  it("counts own feeds that are followed", () => {
    expect(ownCount([feed({}), feed({ builtin: false }), feed({ builtin: false, subscribed: false })])).toBe(1);
  });
});
