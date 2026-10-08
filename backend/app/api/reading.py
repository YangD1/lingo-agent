"""Reading (ADR 0024): the feeds a learner follows (Q41e), their articles, and articles
rewritten for the learner's level (Q42f).

The reading page itself is task 43; these are its data.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, NoReturn

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field

from app.api.errors import api_error
from app.db.models import ArticleVersion, TenantMember
from app.deps import CurrentTenant, CurrentUser, SessionDep, SettingsDep
from app.services.news import feeds
from app.services.news.feeds import ArticleView, FeedError, FeedView
from app.services.reading.versions import ReadingError
from app.services.reading.worker import ReadingWorker

router = APIRouter(prefix="/reading", tags=["reading"])

_ERRORS: dict[str, tuple[int, str]] = {
    "feed_not_found": (status.HTTP_404_NOT_FOUND, "feed not found"),
    "article_not_found": (status.HTTP_404_NOT_FOUND, "article not found"),
    "invalid_url": (status.HTTP_422_UNPROCESSABLE_CONTENT, "not an http(s) feed address"),
    "feed_limit": (
        status.HTTP_409_CONFLICT,
        f"you already follow {feeds.MAX_OWN_FEEDS} feeds of your own",
    ),
    # `reason` carries the fetch error code (not_a_feed, http_404, timeout...).
    "feed_unreachable": (status.HTTP_422_UNPROCESSABLE_CONTENT, "could not read a feed there"),
    "feed_builtin": (status.HTTP_409_CONFLICT, "built-in feeds cannot be deleted"),
    "forbidden": (status.HTTP_403_FORBIDDEN, "only who added the feed or an admin can delete it"),
    "version_not_found": (status.HTTP_404_NOT_FOUND, "version not found"),
    # Not rewritten (Q42a, Q42i, Q41d): the page shows the original instead.
    "summary_only": (status.HTTP_409_CONFLICT, "only a summary: read it at the source"),
    "not_rewritable": (status.HTTP_409_CONFLICT, "this article's license allows no rewriting"),
    "level_above": (status.HTTP_409_CONFLICT, "your level reads the original"),
}


def get_worker(request: Request) -> ReadingWorker:
    worker: ReadingWorker = request.app.state.reading_worker
    return worker


WorkerDep = Annotated[ReadingWorker, Depends(get_worker)]


def _raise(exc: FeedError | ReadingError) -> NoReturn:
    code, message = _ERRORS[exc.code]
    detail = exc.detail if isinstance(exc, FeedError) else None
    error = api_error(code, exc.code, f"{message}: {detail}" if detail else message)
    if detail:
        error.detail["reason"] = detail  # type: ignore[index]
    raise error from exc


class FeedOut(BaseModel):
    id: uuid.UUID
    title: str
    url: str
    site_url: str | None
    builtin: bool
    license: str
    subscribed: bool
    # Whether this learner may delete it (own feeds: who added it, or an admin).
    can_delete: bool
    last_fetched_at: datetime | None
    # Error code of the last failed fetch, until one succeeds.
    last_error: str | None


class FeedsOut(BaseModel):
    feeds: list[FeedOut]
    max_own: int


async def _is_manager(session: SessionDep, tenant_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    member = await session.get(TenantMember, (tenant_id, user_id))
    return member is not None and member.role in ("owner", "admin")


def _feed_out(view: FeedView, user_id: uuid.UUID, *, manager: bool) -> FeedOut:
    feed = view.feed
    return FeedOut(
        id=feed.id,
        title=feed.title,
        url=feed.url,
        site_url=feed.site_url,
        builtin=feed.builtin_key is not None,
        license=feed.license,
        subscribed=view.subscribed,
        can_delete=feeds.can_delete(feed, user_id, manager=manager),
        last_fetched_at=feed.last_fetched_at,
        last_error=feed.last_error,
    )


async def _feeds_out(session: SessionDep, user: CurrentUser, tenant: CurrentTenant) -> FeedsOut:
    manager = await _is_manager(session, tenant.id, user.id)
    views = await feeds.list_feeds(session, user.id, tenant.id)
    return FeedsOut(
        feeds=[_feed_out(v, user.id, manager=manager) for v in views],
        max_own=feeds.MAX_OWN_FEEDS,
    )


@router.get("/feeds")
async def list_feeds(user: CurrentUser, tenant: CurrentTenant, session: SessionDep) -> FeedsOut:
    """Built-in feeds and this tenant's own, with whether this learner follows each."""
    return await _feeds_out(session, user, tenant)


class AddFeedIn(BaseModel):
    url: str = Field(min_length=1, max_length=2000)


@router.post("/feeds", status_code=status.HTTP_201_CREATED)
async def add_feed(
    body: AddFeedIn,
    user: CurrentUser,
    tenant: CurrentTenant,
    session: SessionDep,
    settings: SettingsDep,
) -> FeedsOut:
    """Follow an RSS / Atom address; a new one is fetched once first and saved only if
    it is a readable feed."""
    try:
        await feeds.add_feed(session, user.id, tenant.id, body.url, proxy=settings.feed_http_proxy)
    except FeedError as exc:
        _raise(exc)
    await session.commit()
    return await _feeds_out(session, user, tenant)


class SubscriptionIn(BaseModel):
    subscribed: bool


@router.put("/feeds/{feed_id}/subscription")
async def set_subscription(
    feed_id: uuid.UUID,
    body: SubscriptionIn,
    user: CurrentUser,
    tenant: CurrentTenant,
    session: SessionDep,
) -> FeedsOut:
    try:
        feed = await feeds.get_visible(session, feed_id, tenant.id)
        await feeds.set_subscribed(session, user.id, feed, body.subscribed)
    except FeedError as exc:
        _raise(exc)
    await session.commit()
    return await _feeds_out(session, user, tenant)


@router.delete("/feeds/{feed_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_feed(
    feed_id: uuid.UUID, user: CurrentUser, tenant: CurrentTenant, session: SessionDep
) -> None:
    """Remove an own feed and its articles for the whole tenant."""
    try:
        feed = await feeds.get_visible(session, feed_id, tenant.id)
        if feed.tenant_id is None:
            raise FeedError("feed_builtin")
        manager = await _is_manager(session, tenant.id, user.id)
        if not feeds.can_delete(feed, user.id, manager=manager):
            raise FeedError("forbidden")
    except FeedError as exc:
        _raise(exc)
    await session.delete(feed)
    await session.commit()


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ArticleBriefOut(_Out):
    id: int
    feed_id: uuid.UUID
    feed_title: str
    title: str
    url: str
    author: str | None
    published_at: datetime
    word_count: int
    # Only a teaser: show it with a link to the original, never rewrite it.
    summary_only: bool
    license: str
    tags: list[str]


class ArticleOut(ArticleBriefOut):
    # Paragraphs separated by blank lines, no markup.
    body: str
    site_url: str | None


class ArticlesOut(BaseModel):
    articles: list[ArticleBriefOut]
    # Pass as `before` for the next page; null on the last.
    next_cursor: str | None


def _brief(view: ArticleView) -> dict[str, object]:
    a = view.article
    return {
        "id": a.id,
        "feed_id": a.feed_id,
        "feed_title": view.feed.title,
        "title": a.title,
        "url": a.url,
        "author": a.author,
        "published_at": a.published_at,
        "word_count": a.word_count,
        "summary_only": a.summary_only,
        "license": a.license,
        "tags": a.tags,
    }


_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_MICROSECOND = timedelta(microseconds=1)


def _cursor(view: ArticleView) -> str:
    # Microseconds since the epoch: nothing in it needs escaping in a query string.
    micros = (view.article.published_at - _EPOCH) // _MICROSECOND
    return f"{micros}_{view.article.id}"


def _parse_cursor(value: str) -> tuple[datetime, int]:
    try:
        micros, article_id = value.split("_")
        return _EPOCH + int(micros) * _MICROSECOND, int(article_id)
    except (ValueError, OverflowError, OSError) as exc:
        raise api_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid_cursor", "bad `before` cursor"
        ) from exc


@router.get("/articles")
async def list_articles(
    user: CurrentUser,
    tenant: CurrentTenant,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
    before: str | None = None,
) -> ArticlesOut:
    """Newest first, from the feeds this learner follows."""
    views = await feeds.list_articles(
        session,
        user.id,
        tenant.id,
        limit=limit,
        before=_parse_cursor(before) if before else None,
    )
    return ArticlesOut(
        articles=[ArticleBriefOut.model_validate(_brief(v)) for v in views],
        next_cursor=_cursor(views[-1]) if len(views) == limit else None,
    )


@router.get("/articles/{article_id}")
async def get_article(
    article_id: int, user: CurrentUser, tenant: CurrentTenant, session: SessionDep
) -> ArticleOut:
    try:
        view = await feeds.get_article(session, article_id, tenant.id)
    except FeedError as exc:
        _raise(exc)
    return ArticleOut.model_validate(
        {**_brief(view), "body": view.article.body, "site_url": view.feed.site_url}
    )


class GlossaryWordOut(BaseModel):
    word: str
    word_id: int
    # As first used in the text, lowercase.
    form: str


class QuestionOut(BaseModel):
    question: str
    options: list[str]


class VersionOut(BaseModel):
    id: uuid.UUID
    article: ArticleBriefOut
    level: str
    # generating -> ready | failed.
    status: str
    # While generating: rewriting, reviewing (the critic), fixing (rejected questions).
    stage: str | None
    error_code: str | None
    title: str | None
    paragraphs: list[str]
    word_count: int
    glossary: list[GlossaryWordOut]
    # Without answers (task 43 grades them); empty when none passed the critic.
    questions: list[QuestionOut]


def _version_out(version: ArticleVersion, view: ArticleView, worker: ReadingWorker) -> VersionOut:
    return VersionOut(
        id=version.id,
        article=ArticleBriefOut.model_validate(_brief(view)),
        level=version.level,
        status=version.status,
        stage=worker.stage(version.id) if version.status == "generating" else None,
        error_code=version.error_code,
        title=version.title,
        paragraphs=version.paragraphs,
        word_count=version.word_count,
        glossary=[GlossaryWordOut.model_validate(w) for w in version.glossary],
        questions=[
            QuestionOut(question=q["question"], options=q["options"]) for q in version.questions
        ],
    )


async def _load_version(
    session: SessionDep, version_id: uuid.UUID, tenant_id: uuid.UUID
) -> tuple[ArticleVersion, ArticleView]:
    version = await session.get(ArticleVersion, version_id, populate_existing=True)
    if version is None or version.tenant_id != tenant_id:
        raise FeedError("version_not_found")
    try:
        view = await feeds.get_article(session, version.article_id, tenant_id)
    except FeedError as exc:  # the feed was deleted, or is another tenant's
        raise FeedError("version_not_found") from exc
    return version, view


@router.post("/articles/{article_id}/version")
async def open_version(
    article_id: int,
    user: CurrentUser,
    tenant: CurrentTenant,
    session: SessionDep,
    worker: WorkerDep,
) -> VersionOut:
    """The article at my level: the cached version, or one being written now (poll
    `GET /reading/versions/{id}` while `status` is `generating`)."""
    try:
        version_id = await worker.request(user.id, tenant.id, article_id)
        version, view = await _load_version(session, version_id, tenant.id)
    except (FeedError, ReadingError) as exc:
        _raise(exc)
    return _version_out(version, view, worker)


@router.get("/versions/{version_id}")
async def get_version(
    version_id: uuid.UUID,
    user: CurrentUser,
    tenant: CurrentTenant,
    session: SessionDep,
    worker: WorkerDep,
) -> VersionOut:
    try:
        version, view = await _load_version(session, version_id, tenant.id)
    except FeedError as exc:
        _raise(exc)
    return _version_out(version, view, worker)
