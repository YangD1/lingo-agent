"""What a learner reads: the feeds they see and follow, and the articles from them (Q41e).

Built-in feeds are seen by everyone and followed unless turned off; a learner's own
feeds belong to their tenant (one row per address), and each learner follows them or
not. A learner's own feeds' articles are only ever shown inside that tenant (ADR 0024
§3: their license is unknown).
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx2
from sqlalchemy import ColumnElement, and_, exists, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

from app.db.models import Article, Feed, FeedSubscription
from app.services.news.fetch import make_feed_client
from app.services.news.refresh import refresh_feed
from app.services.news.sources import BUILTIN_SOURCES

# A learner's own feeds they may follow at once (Q41e).
MAX_OWN_FEEDS = 20


class FeedError(Exception):
    """Why a feed could not be added or changed, as an API error code."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(code)
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class FeedView:
    feed: Feed
    subscribed: bool


def _listed() -> ColumnElement[bool]:
    return Feed.builtin_key.in_([s.key for s in BUILTIN_SOURCES])


def _visible(tenant_id: uuid.UUID) -> ColumnElement[bool]:
    return or_(_listed(), Feed.tenant_id == tenant_id)


def _followed(user_id: uuid.UUID) -> ColumnElement[bool]:
    """Built-ins without an opt-out, own feeds with a subscription."""
    row = and_(FeedSubscription.feed_id == Feed.id, FeedSubscription.user_id == user_id)
    return or_(
        _listed() & ~exists().where(row, FeedSubscription.subscribed.is_(False)),
        Feed.tenant_id.is_not(None) & exists().where(row, FeedSubscription.subscribed.is_(True)),
    )


async def followed_feed_ids(
    session: AsyncSession, user_id: uuid.UUID, tenant_id: uuid.UUID
) -> list[uuid.UUID]:
    """The feeds this learner reads: built-ins they did not turn off, own feeds of their
    tenant they follow."""
    return list(
        await session.scalars(select(Feed.id).where(_visible(tenant_id), _followed(user_id)))
    )


async def list_feeds(
    session: AsyncSession, user_id: uuid.UUID, tenant_id: uuid.UUID
) -> list[FeedView]:
    feeds = list(
        await session.scalars(select(Feed).where(_visible(tenant_id)).order_by(Feed.created_at))
    )
    followed = set(
        await session.scalars(
            select(Feed.id).where(Feed.id.in_([f.id for f in feeds]), _followed(user_id))
        )
    )
    # Built-ins first, in their listed order; then own feeds, oldest first.
    order = {s.key: i for i, s in enumerate(BUILTIN_SOURCES)}
    feeds.sort(key=lambda f: order.get(f.builtin_key or "", len(order)))
    return [FeedView(f, f.id in followed) for f in feeds]


async def get_visible(session: AsyncSession, feed_id: uuid.UUID, tenant_id: uuid.UUID) -> Feed:
    feed = await session.scalar(select(Feed).where(Feed.id == feed_id, _visible(tenant_id)))
    if feed is None:
        raise FeedError("feed_not_found")
    return feed


async def set_subscribed(
    session: AsyncSession, user_id: uuid.UUID, feed: Feed, subscribed: bool
) -> None:
    """Caller commits."""
    if subscribed and feed.tenant_id is not None:
        await _check_own_limit(session, user_id, feed.id)
    await session.execute(
        insert(FeedSubscription)
        .values(user_id=user_id, feed_id=feed.id, subscribed=subscribed)
        .on_conflict_do_update(
            index_elements=["user_id", "feed_id"], set_={"subscribed": subscribed}
        )
    )


async def _check_own_limit(
    session: AsyncSession, user_id: uuid.UUID, feed_id: uuid.UUID | None
) -> None:
    """`feed_id`: the own feed about to be followed; None for a new one."""
    following = set(
        await session.scalars(
            select(FeedSubscription.feed_id)
            .join(Feed, Feed.id == FeedSubscription.feed_id)
            .where(
                FeedSubscription.user_id == user_id,
                FeedSubscription.subscribed.is_(True),
                Feed.tenant_id.is_not(None),
            )
        )
    )
    if feed_id not in following and len(following) >= MAX_OWN_FEEDS:
        raise FeedError("feed_limit")


def normalize_url(url: str) -> str:
    try:
        parsed = httpx2.URL(url.strip())
    except httpx2.InvalidURL as exc:
        raise FeedError("invalid_url") from exc
    if parsed.scheme not in ("http", "https") or not parsed.host or parsed.userinfo:
        raise FeedError("invalid_url")
    normalized = str(parsed.copy_with(fragment=None))
    if len(normalized) > 2000:
        raise FeedError("invalid_url")
    return normalized


async def add_feed(
    session: AsyncSession,
    user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    url: str,
    *,
    proxy: str,
) -> Feed:
    """Follow the feed at `url`, adding it to the tenant after one successful fetch.

    A built-in or a feed the tenant already has is just followed. Caller commits; on
    FeedError nothing has been written.
    """
    url = normalize_url(url)
    feed = await session.scalar(
        select(Feed).where(Feed.url == url, or_(_listed(), Feed.tenant_id == tenant_id))
    )
    if feed is not None:
        await set_subscribed(session, user_id, feed, True)
        return feed
    await _check_own_limit(session, user_id, None)
    feed = Feed(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        url=url,
        title=url[:300],
        license="unknown",
        created_by=user_id,
    )
    session.add(feed)
    await session.flush()
    async with make_feed_client(proxy) as client:
        result = await refresh_feed(
            session, client, feed, now=datetime.now(UTC), resolve=bool(proxy)
        )
    if result.error is not None:
        await session.rollback()
        raise FeedError("feed_unreachable", result.error)
    await set_subscribed(session, user_id, feed, True)
    return feed


def can_delete(feed: Feed, user_id: uuid.UUID, *, manager: bool) -> bool:
    """Own feeds only: by whoever added it, or a tenant owner / admin."""
    return feed.tenant_id is not None and (manager or feed.created_by == user_id)


@dataclass(frozen=True)
class ArticleView:
    article: Article
    feed: Feed


async def list_articles(
    session: AsyncSession,
    user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    *,
    limit: int,
    before: tuple[datetime, int] | None,
) -> list[ArticleView]:
    """Newest first from the feeds this learner follows; `before` is the last seen
    (published_at, id)."""
    query = (
        select(Article, Feed)
        .join(Feed, Feed.id == Article.feed_id)
        .where(_visible(tenant_id), _followed(user_id))
        .order_by(Article.published_at.desc(), Article.id.desc())
        .limit(limit)
    )
    if before is not None:
        published_at, article_id = before
        query = query.where(
            or_(
                Article.published_at < published_at,
                and_(Article.published_at == published_at, Article.id < article_id),
            )
        )
    rows = await session.execute(query)
    return [ArticleView(article, feed) for article, feed in rows]


async def get_article(session: AsyncSession, article_id: int, tenant_id: uuid.UUID) -> ArticleView:
    """Any article from a feed the learner can see, followed or not (links stay valid)."""
    row = (
        await session.execute(
            select(Article, Feed)
            .join(Feed, Feed.id == Article.feed_id)
            .where(Article.id == article_id, _visible(tenant_id))
            .options(undefer(Article.body))
        )
    ).first()
    if row is None:
        raise FeedError("article_not_found")
    article, feed = row
    return ArticleView(article, feed)
