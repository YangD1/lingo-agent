"use client";

import { Settings2Icon } from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";
import Link from "next/link";
import { useEffect, useState } from "react";

import { AiBadge } from "@/components/ai-badge";
import { CatLoading } from "@/components/brand/lingo-cat";
import { FeedsSheet } from "@/components/reading/feeds-sheet";
import { useDescribeError } from "@/components/settings/use-describe-error";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorText } from "@/components/ui/error-text";
import { Tag } from "@/components/ui/tag";
import { type ArticleItem, type Feed, fetchArticles, fetchFeeds } from "@/lib/reading";
import { cn } from "@/lib/utils";

/**
 * Graded reading (task 43.4): articles of the feeds I follow, newest first, filtered by
 * feed (Q43f). Opening one rewrites it for my level, unless that is done already.
 */
export function ReadingList() {
  const t = useTranslations("reading.list");
  const describe = useDescribeError();
  const [feeds, setFeeds] = useState<Feed[] | null>(null);
  const [maxOwn, setMaxOwn] = useState(0);
  const [feedId, setFeedId] = useState<string | null>(null);
  const [articles, setArticles] = useState<ArticleItem[] | null>(null);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [managing, setManaging] = useState(false);
  // Bumped when the feeds change, so the list reloads with them.
  const [version, setVersion] = useState(0);

  useEffect(() => {
    fetchFeeds().then(
      (f) => {
        setFeeds(f.feeds);
        setMaxOwn(f.max_own);
      },
      (e: unknown) => setError(describe(e)),
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps -- once
  }, []);

  useEffect(() => {
    let current = true;
    fetchArticles({ feedId }).then(
      (page) => {
        if (!current) return;
        setArticles(page.articles);
        setCursor(page.next_cursor);
      },
      (e: unknown) => current && setError(describe(e)),
    );
    return () => {
      current = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- describe is stable enough
  }, [feedId, version]);

  async function more() {
    if (!cursor || loadingMore) return;
    setLoadingMore(true);
    try {
      const page = await fetchArticles({ feedId, before: cursor });
      setArticles((prev) => [...(prev ?? []), ...page.articles]);
      setCursor(page.next_cursor);
    } catch (e) {
      setError(describe(e));
    } finally {
      setLoadingMore(false);
    }
  }

  // The list loads again: show the cat, not the old articles.
  function reload() {
    setArticles(null);
    setError(null);
  }

  function filter(id: string | null) {
    if (id === feedId) return;
    reload();
    setFeedId(id);
  }

  function feedsChanged(next: Feed[]) {
    setFeeds(next);
    reload();
    // A feed filtered on and then turned off or deleted: back to all.
    if (feedId && !next.some((f) => f.id === feedId && f.subscribed)) setFeedId(null);
    setVersion((v) => v + 1);
  }

  const followed = feeds?.filter((f) => f.subscribed) ?? [];

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="mx-auto flex max-w-2xl flex-col gap-3.5 p-4 md:gap-4 md:px-10 md:py-8">
        <header className="flex flex-wrap items-start justify-between gap-3">
          <div className="flex min-w-0 flex-col gap-1">
            <h1 className="text-xl font-semibold">{t("title")}</h1>
            <p className="flex flex-wrap items-center gap-1.5 text-sm text-muted-foreground">
              {t("description")}
              <AiBadge feature="reading_rewrite" />
            </p>
          </div>
          <Button variant="outline" size="sm" onClick={() => setManaging(true)} data-testid="manage-feeds">
            <Settings2Icon aria-hidden />
            {t("manage")}
          </Button>
        </header>

        {followed.length > 1 && (
          <div className="flex flex-wrap gap-1.5" role="group" aria-label={t("filter")}>
            <Chip selected={feedId === null} onClick={() => filter(null)}>
              {t("all")}
            </Chip>
            {followed.map((f) => (
              <Chip key={f.id} selected={feedId === f.id} onClick={() => filter(f.id)}>
                {f.title}
              </Chip>
            ))}
          </div>
        )}

        {error && <ErrorText>{error}</ErrorText>}
        {articles === null && !error && <CatLoading size={48} label={t("loading")} />}
        {articles?.length === 0 && (
          <EmptyState
            title={t(followed.length === 0 ? "noFeeds" : "empty")}
            description={t(followed.length === 0 ? "noFeedsHint" : "emptyHint")}
            action={
              <Button variant="outline" size="sm" onClick={() => setManaging(true)}>
                {t("manage")}
              </Button>
            }
          />
        )}
        {articles && articles.length > 0 && (
          <ul className="flex flex-col gap-2" aria-label={t("title")}>
            {articles.map((a) => (
              <li key={a.id}>
                <ArticleRow article={a} />
              </li>
            ))}
          </ul>
        )}
        {cursor && articles && (
          <Button variant="ghost" disabled={loadingMore} onClick={() => void more()} className="self-center">
            {loadingMore ? t("loadingMore") : t("more")}
          </Button>
        )}
      </div>
      <FeedsSheet
        open={managing}
        onOpenChange={setManaging}
        feeds={feeds ?? []}
        maxOwn={maxOwn}
        onChange={feedsChanged}
      />
    </div>
  );
}

function ArticleRow({ article: a }: { article: ArticleItem }) {
  const t = useTranslations("reading.list");
  const format = useFormatter();
  return (
    <Link
      href={`/reading/${a.id}`}
      data-testid="reading-article"
      className="flex flex-col gap-1.5 rounded-xl border bg-card px-4 py-3 outline-none transition-colors hover:bg-accent/50 focus-visible:outline-2 focus-visible:outline-ring"
    >
      <span lang="en" className={cn("font-[550] leading-snug", a.read && "text-muted-foreground")}>
        {a.title}
      </span>
      <span className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
        <span>{a.feed_title}</span>
        <span aria-hidden>·</span>
        <time dateTime={a.published_at}>{format.dateTime(new Date(a.published_at), { dateStyle: "medium" })}</time>
        {!a.summary_only && (
          <>
            <span aria-hidden>·</span>
            <span className="tabular-nums">{t("words", { n: a.word_count })}</span>
          </>
        )}
        {a.rewritten && <Tag variant="brand">{t("rewritten")}</Tag>}
        {a.summary_only && <Tag variant="outline">{t("summaryOnly")}</Tag>}
        {a.read && <Tag>{t("read")}</Tag>}
      </span>
    </Link>
  );
}

function Chip({
  selected,
  onClick,
  children,
}: {
  selected: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      aria-pressed={selected}
      onClick={onClick}
      className={cn(
        "rounded-full border px-3 py-1 text-xs font-medium transition-colors outline-none hover:bg-accent focus-visible:outline-2 focus-visible:outline-ring",
        selected && "border-primary bg-brand-soft text-brand-soft-foreground hover:bg-brand-soft",
      )}
    >
      {children}
    </button>
  );
}
