"""Fetching feeds into `articles` (ADR 0024 §6; Q41e-g).

`fetch_due_feeds` is the scheduled `rss_fetch` job's work: every feed someone reads
whose next fetch is due, a few at a time, each in its own transaction so one bad feed
never holds up the rest. `refresh_feed` does one feed; adding a learner's own feed
calls it too, to check the address before saving it.
"""

import asyncio
import logging
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import httpx2
from sqlalchemy import ColumnElement, delete, exists, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Article, Feed, FeedSubscription, User
from app.services.news.fetch import FeedFetchError, fetch_feed, make_feed_client
from app.services.news.parse import ParsedFeed, parse_feed
from app.services.news.rules import Kept, judge
from app.services.news.sources import BUILTIN_SOURCES

logger = logging.getLogger(__name__)

# How often a feed is fetched (ADR 0024 §6). The next fetch is set a little short of
# this, so a feed fetched late in one run is still due in the next.
FETCH_INTERVAL = timedelta(hours=2)
_SLACK = timedelta(minutes=10)
# After this many failures in a row the wait doubles, up to MAX_BACKOFF (Q41f).
BACKOFF_AFTER = 3
MAX_BACKOFF = timedelta(hours=24)
# Articles older than this are removed unless something refers to them (Q41g).
RETENTION = timedelta(days=90)
CONCURRENCY = 4


@dataclass
class FeedResult:
    # Entries stored this time; 0 when the feed had not changed.
    added: int = 0
    skipped: Counter[str] = field(default_factory=Counter)
    # Error code when the fetch failed; the feed keeps its old articles.
    error: str | None = None


def next_fetch(now: datetime, failures: int) -> datetime:
    if failures < BACKOFF_AFTER:
        return now + FETCH_INTERVAL - _SLACK
    wait: timedelta = FETCH_INTERVAL * (2 ** (failures - BACKOFF_AFTER + 1))
    return now + min(wait, MAX_BACKOFF) - _SLACK


@dataclass(frozen=True)
class _Extracted:
    feed: ParsedFeed
    articles: list[tuple[int, Kept]]  # index into feed.entries
    skipped: Counter[str]


def _extract(content: bytes, source: str | None, license: str, now: datetime) -> _Extracted:
    feed = parse_feed(content, now=now)
    articles: list[tuple[int, Kept]] = []
    skipped: Counter[str] = Counter()
    for i, entry in enumerate(feed.entries):
        if entry.published_at < now - RETENTION:
            skipped["old"] += 1  # would be removed again at the end of the run
            continue
        result = judge(entry, source=source, feed_license=license)
        if isinstance(result, Kept):
            articles.append((i, result))
        else:
            skipped[result.reason] += 1
    return _Extracted(feed, articles, skipped)


async def refresh_feed(
    session: AsyncSession,
    client: httpx2.AsyncClient,
    feed: Feed,
    *,
    now: datetime,
    resolve: bool,
) -> FeedResult:
    """Fetch one feed and store its new entries; the caller commits.

    A failure is recorded on the feed (and backs off) rather than raised.
    """
    result = FeedResult()
    try:
        fetched = await fetch_feed(
            client, feed.url, etag=feed.etag, last_modified=feed.last_modified, resolve=resolve
        )
        extracted = None
        if fetched.content is not None:
            # Parsing and cleaning are CPU work: keep them off the event loop.
            extracted = await asyncio.to_thread(
                _extract, fetched.content, feed.builtin_key, feed.license, now
            )
    except FeedFetchError as exc:
        result.error = exc.code
        feed.failures += 1
        feed.last_error = exc.code
        feed.next_fetch_at = next_fetch(now, feed.failures)
        return result

    if extracted is not None:
        result.skipped = extracted.skipped
        rows = [
            {
                "feed_id": feed.id,
                "guid": entry.guid,
                "url": entry.url,
                "title": entry.title or entry.url,
                "author": entry.author,
                "published_at": entry.published_at,
                "body": kept.body,
                "summary_only": kept.summary_only,
                "license": kept.license,
                "word_count": kept.word_count,
                "tags": list(entry.tags),
            }
            for i, kept in extracted.articles
            for entry in [extracted.feed.entries[i]]
        ]
        if rows:
            inserted = await session.scalars(
                insert(Article)
                .values(rows)
                .on_conflict_do_nothing(index_elements=["feed_id", "guid"])
                .returning(Article.id)
            )
            result.added = len(inserted.all())
        if feed.builtin_key is None:
            # A learner's own feed is named by the feed; built-ins keep their listed names.
            feed.title = extracted.feed.title or feed.title
            feed.site_url = extracted.feed.site_url or feed.site_url
    feed.etag, feed.last_modified = fetched.etag, fetched.last_modified
    feed.last_fetched_at = now
    feed.failures = 0
    feed.last_error = None
    feed.next_fetch_at = next_fetch(now, 0)
    return result


def _read_by_someone() -> ColumnElement[bool]:
    """Feeds worth fetching (Q41e): a listed built-in that not every learner turned off,
    or a learner's own feed that someone follows."""
    opted_out = (
        select(func.count())
        .select_from(FeedSubscription)
        .where(FeedSubscription.feed_id == Feed.id, FeedSubscription.subscribed.is_(False))
        .scalar_subquery()
    )
    users = select(func.count()).select_from(User).scalar_subquery()
    followed = exists().where(
        FeedSubscription.feed_id == Feed.id, FeedSubscription.subscribed.is_(True)
    )
    listed = [s.key for s in BUILTIN_SOURCES]
    return or_(
        Feed.builtin_key.in_(listed) & (opted_out < users),
        Feed.tenant_id.is_not(None) & followed,
    )


async def fetch_due_feeds(
    sessionmaker: async_sessionmaker[AsyncSession], *, now: datetime, proxy: str
) -> Counter[str]:
    """One `rss_fetch` run; returns counts for the log."""
    async with sessionmaker() as session:
        due = list(
            await session.scalars(
                select(Feed.id).where(
                    or_(Feed.next_fetch_at.is_(None), Feed.next_fetch_at <= now),
                    _read_by_someone(),
                )
            )
        )
    totals: Counter[str] = Counter()
    limit = asyncio.Semaphore(CONCURRENCY)

    async def one(feed_id: object) -> None:
        async with limit, sessionmaker() as session:
            feed = await session.get(Feed, feed_id)
            if feed is None:
                return  # deleted meanwhile
            try:
                result = await refresh_feed(session, client, feed, now=now, resolve=bool(proxy))
                await session.commit()
            except Exception:
                logger.exception("fetching feed %s failed", feed_id)
                await session.rollback()
                totals["failed"] += 1
                # Back off as for a failed fetch, so a feed that trips a bug is not
                # retried every run.
                feed = await session.get(Feed, feed_id)
                if feed is not None:
                    feed.failures += 1
                    feed.last_error = "internal"
                    feed.next_fetch_at = next_fetch(now, feed.failures)
                    await session.commit()
                return
        totals["fetched"] += 1
        totals["added"] += result.added
        totals["failed"] += result.error is not None
        totals.update({f"skipped_{k}": v for k, v in result.skipped.items()})

    async with make_feed_client(proxy) as client:
        await asyncio.gather(*(one(feed_id) for feed_id in due))

    async with sessionmaker() as session:
        removed = await session.execute(
            # Task 42/43: keep articles that have rewrites or reading sessions.
            delete(Article).where(Article.published_at < now - RETENTION)
        )
        await session.commit()
    totals["removed"] = removed.rowcount  # type: ignore[attr-defined]
    logger.info("rss_fetch: %s", dict(totals))
    return totals
