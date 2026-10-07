"""`feeds`, `feed_subscriptions`, `articles` and the built-in feed sync (task 41.1)."""

import uuid
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Article, Feed, FeedSubscription, Tenant, User
from app.services.news import sources
from app.services.news.sources import BUILTIN_SOURCES, sync_builtin_feeds


async def _tenant(session: AsyncSession) -> Tenant:
    tenant = Tenant(name="t", kind="personal")
    session.add(tenant)
    await session.flush()
    return tenant


def _own_feed(tenant: Tenant, url: str = "https://example.com/feed.xml") -> Feed:
    return Feed(tenant_id=tenant.id, url=url, title=url, license="unknown")


def _article(feed: Feed, guid: str = "a1") -> Article:
    return Article(
        feed_id=feed.id,
        guid=guid,
        url="https://example.com/a1",
        title="A title",
        published_at=datetime(2026, 10, 7, tzinfo=UTC),
        body="One.\n\nTwo.",
        summary_only=False,
        license="unknown",
        word_count=2,
    )


async def test_sync_adds_each_builtin_once(db_session: AsyncSession) -> None:
    await sync_builtin_feeds(db_session)
    await db_session.flush()
    await sync_builtin_feeds(db_session)
    await db_session.flush()

    feeds = (await db_session.scalars(select(Feed).order_by(Feed.builtin_key))).all()
    assert [f.builtin_key for f in feeds] == sorted(s.key for s in BUILTIN_SOURCES)
    assert all(f.tenant_id is None for f in feeds)
    licenses = {f.builtin_key: f.license for f in feeds}
    assert licenses == {"global_voices": "cc_by", "nasa": "public_domain"}


async def test_sync_follows_a_moved_builtin(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    await sync_builtin_feeds(db_session)
    await db_session.flush()
    nasa = await db_session.scalar(select(Feed).where(Feed.builtin_key == "nasa"))
    assert nasa is not None
    nasa.etag, nasa.last_modified = '"abc"', "Wed, 07 Oct 2026 14:47:33 GMT"
    nasa.next_fetch_at = datetime(2026, 10, 7, 16, tzinfo=UTC)
    await db_session.flush()

    moved = tuple(
        replace(s, url="https://www.nasa.gov/feed/") if s.key == "nasa" else s
        for s in BUILTIN_SOURCES
    )
    monkeypatch.setattr(sources, "BUILTIN_SOURCES", moved)
    await sync_builtin_feeds(db_session)
    await db_session.flush()

    await db_session.refresh(nasa)
    assert nasa.url == "https://www.nasa.gov/feed/"
    assert (nasa.etag, nasa.last_modified, nasa.next_fetch_at) == (None, None, None)
    assert await db_session.scalar(select(func.count()).select_from(Feed)) == len(BUILTIN_SOURCES)


async def test_a_builtin_has_no_tenant_and_an_own_feed_has_one(db_session: AsyncSession) -> None:
    tenant = await _tenant(db_session)
    db_session.add(
        Feed(tenant_id=tenant.id, builtin_key="x", url="https://e.com", title="x", license="cc_by")
    )
    with pytest.raises(IntegrityError, match="builtin"):
        await db_session.flush()


async def test_a_tenant_adds_an_address_once(db_session: AsyncSession) -> None:
    tenant, other = await _tenant(db_session), await _tenant(db_session)
    db_session.add_all([_own_feed(tenant), _own_feed(other)])
    await db_session.flush()  # the same address in two tenants is two feeds

    db_session.add(_own_feed(tenant))
    with pytest.raises(IntegrityError, match="uq_feeds_tenant_id_url"):
        await db_session.flush()


async def test_an_entry_is_stored_once_per_feed(db_session: AsyncSession) -> None:
    feed = _own_feed(await _tenant(db_session))
    db_session.add(feed)
    await db_session.flush()
    db_session.add(_article(feed))
    await db_session.flush()

    db_session.add(_article(feed))
    with pytest.raises(IntegrityError, match="uq_articles_feed_id_guid"):
        await db_session.flush()


async def test_deleting_a_feed_deletes_its_articles_and_subscriptions(
    db_session: AsyncSession,
) -> None:
    tenant = await _tenant(db_session)
    user = User(email=f"{uuid.uuid4()}@example.com", password_hash="x")
    feed = _own_feed(tenant)
    db_session.add_all([user, feed])
    await db_session.flush()
    feed.created_by = user.id
    db_session.add_all(
        [_article(feed), FeedSubscription(user_id=user.id, feed_id=feed.id, subscribed=True)]
    )
    await db_session.flush()

    # The learner who added it leaves: the tenant keeps the feed.
    await db_session.execute(delete(User).where(User.id == user.id))
    await db_session.refresh(feed)
    assert feed.created_by is None
    assert await db_session.scalar(select(func.count()).select_from(FeedSubscription)) == 0

    await db_session.execute(delete(Feed).where(Feed.id == feed.id))
    assert await db_session.scalar(select(func.count()).select_from(Article)) == 0
