"""Reading API: feeds a learner sees and follows, their own feeds, articles (task 41.4)."""

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx2
import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Article, Feed
from app.services.news import feeds as feeds_service
from app.services.news.sources import sync_builtin_feeds

FEEDS = Path(__file__).parent.parent / "fixtures" / "feeds"
OWN = "https://daily.example/rss"


async def login(client: AsyncClient) -> uuid.UUID:
    email = f"{uuid.uuid4()}@example.com"
    response = await client.post("/auth/register", json={"email": email, "password": "password123"})
    assert response.status_code == 201
    return uuid.UUID(response.json()["id"])


@pytest.fixture(autouse=True)
async def builtins(db_session: AsyncSession) -> None:
    await sync_builtin_feeds(db_session)
    await db_session.commit()


@pytest.fixture(autouse=True)
def web(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Own-feed addresses: OWN serves an RSS feed, /page a web page, the rest 404."""
    requested: list[str] = []

    def handle(request: httpx2.Request) -> httpx2.Response:
        requested.append(str(request.url))
        if str(request.url) == OWN:
            return httpx2.Response(200, content=(FEEDS / "summary_only.xml").read_bytes())
        if request.url.path == "/page":
            return httpx2.Response(200, content=(FEEDS / "not_a_feed.html").read_bytes())
        return httpx2.Response(404)

    monkeypatch.setattr(
        feeds_service,
        "make_feed_client",
        lambda proxy: httpx2.AsyncClient(transport=httpx2.MockTransport(handle)),
    )
    return requested


async def add_article(session: AsyncSession, key: str, title: str, published: datetime) -> int:
    feed = await session.scalar(select(Feed).where(Feed.builtin_key == key))
    assert feed is not None
    article = Article(
        feed_id=feed.id,
        guid=title,
        url=f"https://example.com/{uuid.uuid4()}",
        title=title,
        published_at=published,
        body="One.\n\nTwo.",
        summary_only=False,
        license=feed.license,
        word_count=300,
        tags=["Space"],
    )
    session.add(article)
    await session.commit()
    return article.id


def by_title(body: dict[str, list[dict[str, object]]]) -> dict[object, dict[str, object]]:
    return {f["title"]: f for f in body["feeds"]}


async def test_endpoints_require_login(client: AsyncClient) -> None:
    for path in ("/reading/feeds", "/reading/articles", "/reading/articles/1"):
        assert (await client.get(path)).status_code == 401


async def test_builtins_are_listed_and_followed_by_default(client: AsyncClient) -> None:
    await login(client)
    body = (await client.get("/reading/feeds")).json()
    assert body["max_own"] == 20
    assert [
        (f["title"], f["builtin"], f["subscribed"], f["can_delete"]) for f in body["feeds"]
    ] == [
        ("NASA News Releases", True, True, False),
        ("Global Voices", True, True, False),
    ]


async def test_turning_a_builtin_off_is_per_learner(client: AsyncClient) -> None:
    await login(client)
    nasa = by_title((await client.get("/reading/feeds")).json())["NASA News Releases"]
    response = await client.put(
        f"/reading/feeds/{nasa['id']}/subscription", json={"subscribed": False}
    )
    assert by_title(response.json())["NASA News Releases"]["subscribed"] is False

    await login(client)  # another learner
    assert by_title((await client.get("/reading/feeds")).json())["NASA News Releases"]["subscribed"]

    response = await client.put(
        f"/reading/feeds/{uuid.uuid4()}/subscription", json={"subscribed": True}
    )
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "feed_not_found"


async def test_adding_an_own_feed_fetches_it_first(
    client: AsyncClient, db_session: AsyncSession, web: list[str]
) -> None:
    await login(client)
    response = await client.post("/reading/feeds", json={"url": f"  {OWN}#top "})
    assert response.status_code == 201
    own = by_title(response.json())["A Pretend Daily"]
    assert own == {
        **own,
        "url": OWN,
        "builtin": False,
        "license": "unknown",
        "subscribed": True,
        "can_delete": True,
        "last_error": None,
    }
    assert web == [OWN]
    # The first fetch already stored its entries.
    count = await db_session.scalar(select(func.count()).select_from(Article))
    assert count == 2

    # The same address again: followed, not added twice, not fetched again.
    response = await client.post("/reading/feeds", json={"url": OWN})
    assert response.status_code == 201
    assert len(response.json()["feeds"]) == 3
    assert web == [OWN]


async def test_a_bad_address_is_not_saved(client: AsyncClient, db_session: AsyncSession) -> None:
    await login(client)
    cases = {
        "ftp://daily.example/rss": ("invalid_url", None),
        "https://daily.example/page": ("feed_unreachable", "not_a_feed"),
        "https://daily.example/missing": ("feed_unreachable", "http_404"),
    }
    for url, (code, reason) in cases.items():
        response = await client.post("/reading/feeds", json={"url": url})
        assert response.status_code == 422, url
        assert response.json()["detail"]["code"] == code
        assert response.json()["detail"].get("reason") == reason
    assert (
        await db_session.scalar(
            select(func.count()).select_from(Feed).where(Feed.tenant_id.is_not(None))
        )
        == 0
    )


async def test_own_feeds_are_capped(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(feeds_service, "MAX_OWN_FEEDS", 1)
    await login(client)
    assert (await client.post("/reading/feeds", json={"url": OWN})).status_code == 201
    response = await client.post("/reading/feeds", json={"url": "https://other.example/rss"})
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "feed_limit"

    # Turning one off makes room; turning it back on when full does not.
    own = by_title((await client.get("/reading/feeds")).json())["A Pretend Daily"]
    await client.put(f"/reading/feeds/{own['id']}/subscription", json={"subscribed": False})
    response = await client.put(
        f"/reading/feeds/{own['id']}/subscription", json={"subscribed": True}
    )
    assert response.status_code == 200


async def test_deleting_feeds(client: AsyncClient, db_session: AsyncSession) -> None:
    user_id = await login(client)
    body = (await client.post("/reading/feeds", json={"url": OWN})).json()
    own, nasa = by_title(body)["A Pretend Daily"], by_title(body)["NASA News Releases"]

    response = await client.delete(f"/reading/feeds/{nasa['id']}")
    assert (response.status_code, response.json()["detail"]["code"]) == (409, "feed_builtin")

    # Only who added it, or an admin. (A plain member has no tenant to act in yet in P0,
    # so the refusal is checked on the rule itself.)
    feed = await db_session.get(Feed, uuid.UUID(str(own["id"])))
    assert feed is not None
    assert feeds_service.can_delete(feed, user_id, manager=False)
    assert not feeds_service.can_delete(feed, uuid.uuid4(), manager=False)
    assert feeds_service.can_delete(feed, uuid.uuid4(), manager=True)
    feed.created_by = None  # added by someone who has left: the owner may still delete
    await db_session.commit()
    assert (await client.delete(f"/reading/feeds/{own['id']}")).status_code == 204
    assert await db_session.scalar(select(func.count()).select_from(Article)) == 0


async def test_articles_come_from_followed_feeds_newest_first(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await login(client)
    start = datetime(2026, 10, 1, tzinfo=UTC)
    for i in range(3):
        await add_article(db_session, "nasa", f"nasa {i}", start + timedelta(days=i))
    same_time = start + timedelta(days=5)
    await add_article(db_session, "global_voices", "gv a", same_time)
    gv_b = await add_article(db_session, "global_voices", "gv b", same_time)

    pages: list[list[str]] = []
    cursor: str | None = None
    while True:
        params: dict[str, str | int] = {"limit": 2}
        if cursor:
            params["before"] = cursor
        body = (await client.get("/reading/articles", params=params)).json()
        pages.append([a["title"] for a in body["articles"]])
        cursor = body["next_cursor"]
        if cursor is None:
            break
    assert pages == [["gv b", "gv a"], ["nasa 2", "nasa 1"], ["nasa 0"]]

    first = (await client.get("/reading/articles", params={"limit": 1})).json()["articles"][0]
    assert first == {
        **first,
        "id": gv_b,
        "feed_title": "Global Voices",
        "license": "cc_by",
        "summary_only": False,
        "tags": ["Space"],
    }
    assert "body" not in first

    # Turned off: its articles leave the list, but a link to one still opens.
    gv = by_title((await client.get("/reading/feeds")).json())["Global Voices"]
    await client.put(f"/reading/feeds/{gv['id']}/subscription", json={"subscribed": False})
    titles = [a["title"] for a in (await client.get("/reading/articles")).json()["articles"]]
    assert titles == ["nasa 2", "nasa 1", "nasa 0"]
    article = (await client.get(f"/reading/articles/{gv_b}")).json()
    assert (article["body"], article["site_url"]) == ("One.\n\nTwo.", "https://globalvoices.org")

    response = await client.get("/reading/articles", params={"before": "nonsense"})
    assert (response.status_code, response.json()["detail"]["code"]) == (422, "invalid_cursor")


async def test_own_feed_articles_stay_in_their_tenant(client: AsyncClient) -> None:
    await login(client)
    await client.post("/reading/feeds", json={"url": OWN})
    mine = (await client.get("/reading/articles")).json()["articles"]
    assert {a["license"] for a in mine} == {"unknown"}

    await login(client)  # a learner in another tenant
    assert (await client.get("/reading/articles")).json()["articles"] == []
    response = await client.get(f"/reading/articles/{mine[0]['id']}")
    assert (response.status_code, response.json()["detail"]["code"]) == (404, "article_not_found")
    assert [f["title"] for f in (await client.get("/reading/feeds")).json()["feeds"]] == [
        "NASA News Releases",
        "Global Voices",
    ]
