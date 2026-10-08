"""The `rss_fetch` job: which feeds, what is stored, back-off, clean-up (task 41.3; Q41e-g)."""

import uuid
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx2
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.db.models import (
    Article,
    Feed,
    FeedSubscription,
    ReadingSession,
    SchedulerRun,
    Tenant,
    User,
)
from app.db.session import create_sessionmaker
from app.scheduler.jobs import JOBS
from app.scheduler.service import Scheduler
from app.services.news import refresh
from app.services.news.refresh import fetch_due_feeds
from app.services.news.sources import sync_builtin_feeds

FEEDS = Path(__file__).parent.parent / "fixtures" / "feeds"
NOW = datetime(2026, 10, 7, 15, tzinfo=UTC)
OWN_URL = "https://daily.example/rss"


class Web:
    """Serves the fixture feeds; a test can make an address fail or change."""

    def __init__(self) -> None:
        self.pages: dict[str, Callable[[httpx2.Request], httpx2.Response]] = {}
        self.requests: list[str] = []
        self.serve("https://www.nasa.gov/news-release/feed/", "nasa.xml", etag='"n1"')
        self.serve("https://globalvoices.org/feed/", "global_voices.xml", etag='"g1"')
        self.serve(OWN_URL, "summary_only.xml")

    def serve(self, url: str, fixture: str, *, etag: str | None = None) -> None:
        content = (FEEDS / fixture).read_bytes()

        def page(request: httpx2.Request) -> httpx2.Response:
            if etag and request.headers.get("If-None-Match") == etag:
                return httpx2.Response(304)
            return httpx2.Response(200, content=content, headers={"ETag": etag} if etag else {})

        self.pages[url] = page

    def fail(self, url: str, status: int = 404) -> None:
        self.pages[url] = lambda _: httpx2.Response(status)

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(str(request.url))
        return self.pages[str(request.url)](request)


@pytest.fixture
async def maker(
    db_engine: AsyncEngine, db_session: AsyncSession
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    # db_session's teardown truncates the tables after the test.
    maker = create_sessionmaker(db_engine)
    async with maker() as session:
        await sync_builtin_feeds(session)
        await session.commit()
    yield maker


@pytest.fixture
def web(monkeypatch: pytest.MonkeyPatch) -> Web:
    web = Web()
    monkeypatch.setattr(
        refresh,
        "make_feed_client",
        lambda proxy: httpx2.AsyncClient(transport=httpx2.MockTransport(web.handle)),
    )
    return web


async def add_user(maker: async_sessionmaker[AsyncSession]) -> User:
    async with maker() as session:
        user = User(email=f"{uuid.uuid4()}@example.com", password_hash="x")
        session.add(user)
        await session.commit()
        return user


async def add_own_feed(maker: async_sessionmaker[AsyncSession], follower: User | None) -> Feed:
    async with maker() as session:
        tenant = Tenant(name="t", kind="personal")
        session.add(tenant)
        await session.flush()
        feed = Feed(tenant_id=tenant.id, url=OWN_URL, title=OWN_URL, license="unknown")
        session.add(feed)
        await session.flush()
        if follower is not None:
            session.add(FeedSubscription(user_id=follower.id, feed_id=feed.id, subscribed=True))
        await session.commit()
        return feed


async def feeds(maker: async_sessionmaker[AsyncSession]) -> dict[str, Feed]:
    async with maker() as session:
        return {f.builtin_key or f.url: f for f in await session.scalars(select(Feed))}


async def articles(maker: async_sessionmaker[AsyncSession]) -> list[Article]:
    async with maker() as session:
        return list(await session.scalars(select(Article).order_by(Article.title)))


async def test_builtins_are_fetched_and_filtered(
    maker: async_sessionmaker[AsyncSession], web: Web
) -> None:
    await add_user(maker)
    totals = await fetch_due_feeds(maker, now=NOW, proxy="")

    stored = await articles(maker)
    assert [a.title for a in stored] == [
        "A pretend radio station goes online",
        "Pretend Sea Ice Reaches Its Yearly Low",
    ]
    assert {a.license for a in stored} == {"cc_by", "public_domain"}
    assert totals["added"] == 2
    assert totals["skipped_apod"] == totals["skipped_too_short"] == 1
    assert totals["skipped_republished"] == 2

    nasa = (await feeds(maker))["nasa"]
    assert nasa.etag == '"n1"'
    assert nasa.title == "NASA News Releases"  # the listed name, not the feed's own
    assert nasa.last_fetched_at == NOW
    assert nasa.next_fetch_at == NOW + timedelta(hours=2) - timedelta(minutes=10)


async def test_unchanged_and_repeated_entries_are_not_stored_twice(
    maker: async_sessionmaker[AsyncSession], web: Web
) -> None:
    await add_user(maker)
    await fetch_due_feeds(maker, now=NOW, proxy="")

    # Not due yet: nothing is requested.
    web.requests.clear()
    await fetch_due_feeds(maker, now=NOW + timedelta(hours=1), proxy="")
    assert web.requests == []

    # Due, unchanged (304) for NASA; Global Voices serves the same entries again.
    web.serve("https://globalvoices.org/feed/", "global_voices.xml", etag='"g2"')
    later = NOW + timedelta(hours=2)
    totals = await fetch_due_feeds(maker, now=later, proxy="")
    assert totals["fetched"] == 2
    assert totals["added"] == 0
    assert len(await articles(maker)) == 2
    assert (await feeds(maker))["nasa"].last_fetched_at == later


async def test_only_feeds_someone_reads_are_fetched(
    maker: async_sessionmaker[AsyncSession], web: Web
) -> None:
    # Nobody has an account yet, and nobody follows the learner's own feed.
    await add_own_feed(maker, follower=None)
    await fetch_due_feeds(maker, now=NOW, proxy="")
    assert web.requests == []

    # A learner arrives and turns NASA off; Global Voices is on by default.
    user = await add_user(maker)
    async with maker() as session:
        nasa = (await feeds(maker))["nasa"]
        session.add(FeedSubscription(user_id=user.id, feed_id=nasa.id, subscribed=False))
        await session.commit()
    await fetch_due_feeds(maker, now=NOW, proxy="")
    assert web.requests == ["https://globalvoices.org/feed/"]


async def test_an_own_feed_takes_its_name_and_keeps_teasers(
    maker: async_sessionmaker[AsyncSession], web: Web
) -> None:
    user = await add_user(maker)
    await add_own_feed(maker, follower=user)
    await fetch_due_feeds(maker, now=NOW, proxy="")

    feed = (await feeds(maker))[OWN_URL]
    assert (feed.title, feed.site_url) == ("A Pretend Daily", "https://daily.example")
    own = [a for a in await articles(maker) if a.feed_id == feed.id]
    assert [(a.title, a.summary_only, a.license) for a in own] == [
        ("Item from the future", True, "unknown"),
        ("Pretend city opens a new library & park", True, "unknown"),
    ]


async def test_failures_back_off_and_do_not_stop_other_feeds(
    maker: async_sessionmaker[AsyncSession], web: Web
) -> None:
    await add_user(maker)
    web.fail("https://www.nasa.gov/news-release/feed/")
    now = NOW
    waits = []
    for failures in range(1, 5):
        totals = await fetch_due_feeds(maker, now=now, proxy="")
        assert totals["failed"] == 1
        nasa = (await feeds(maker))["nasa"]
        assert (nasa.failures, nasa.last_error) == (failures, "http_404")
        assert nasa.next_fetch_at is not None
        waits.append(nasa.next_fetch_at - now + timedelta(minutes=10))
        now = nasa.next_fetch_at
    assert waits == [timedelta(hours=h) for h in (2, 2, 4, 8)]
    assert refresh.next_fetch(NOW, 9) - NOW == timedelta(hours=24) - timedelta(minutes=10)

    # Global Voices was stored all along; one success clears NASA's record.
    assert any(a.license == "cc_by" for a in await articles(maker))
    web.serve("https://www.nasa.gov/news-release/feed/", "nasa.xml")
    await fetch_due_feeds(maker, now=now, proxy="")
    nasa = (await feeds(maker))["nasa"]
    assert (nasa.failures, nasa.last_error) == (0, None)


async def test_a_bug_in_one_feed_is_recorded_and_backed_off(
    maker: async_sessionmaker[AsyncSession], web: Web, monkeypatch: pytest.MonkeyPatch
) -> None:
    await add_user(maker)
    real = refresh._extract

    def broken(content: bytes, source: str | None, license: str, now: datetime) -> object:
        if source == "nasa":
            raise RuntimeError("bug")
        return real(content, source, license, now)

    monkeypatch.setattr(refresh, "_extract", broken)
    totals = await fetch_due_feeds(maker, now=NOW, proxy="")
    assert totals["failed"] == 1
    nasa = (await feeds(maker))["nasa"]
    assert (nasa.failures, nasa.last_error) == (1, "internal")
    assert len(await articles(maker)) == 1


async def test_old_articles_are_removed_and_never_stored(
    maker: async_sessionmaker[AsyncSession], web: Web
) -> None:
    reader = await add_user(maker)
    long_after = NOW + timedelta(days=91)
    await fetch_due_feeds(maker, now=NOW, proxy="")
    stored = await articles(maker)
    assert len(stored) == 2
    # Someone read one of them: it stays (Q43a).
    async with maker() as session:
        session.add(ReadingSession(user_id=reader.id, article_id=stored[0].id, level="B1"))
        await session.commit()

    # 91 days on, the stored ones are past retention, and the same entries come back
    # in the feed: they are not stored again.
    web.serve("https://www.nasa.gov/news-release/feed/", "nasa.xml", etag='"n2"')
    web.serve("https://globalvoices.org/feed/", "global_voices.xml", etag='"g2"')
    totals = await fetch_due_feeds(maker, now=long_after, proxy="")
    assert totals["removed"] == 1
    assert totals["skipped_old"] == 6
    assert [a.id for a in await articles(maker)] == [stored[0].id]


async def test_the_job_runs_under_the_scheduler(
    maker: async_sessionmaker[AsyncSession], web: Web
) -> None:
    await add_user(maker)
    scheduler = Scheduler(maker, JOBS)
    assert scheduler.trigger("rss_fetch")
    await scheduler.wait("rss_fetch")
    async with maker() as session:
        run = await session.get(SchedulerRun, "rss_fetch")
        count = await session.scalar(select(func.count()).select_from(Article))
    assert run is not None and run.last_status == "ok"
    assert count == 2
