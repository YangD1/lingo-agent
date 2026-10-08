"""Reading (ADR 0024): the feeds a learner follows (Q41e), their articles, articles
rewritten for the learner's level (Q42f), and the learner reading one: the session,
quiz answers and the due words in the text (Q43a, Q43b, Q43d).
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, NoReturn

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.adaptive.rules import get_rules
from app.api.errors import api_error
from app.db.models import Article, ArticleVersion, ReadingSession, TenantMember
from app.deps import CurrentTenant, CurrentUser, SessionDep, SettingsDep
from app.services.news import feeds
from app.services.news.feeds import ArticleView, FeedError, FeedView
from app.services.reading import sessions, versions
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
    "session_not_found": (status.HTTP_404_NOT_FOUND, "reading session not found"),
    "no_questions": (status.HTTP_409_CONFLICT, "this text has no questions to answer"),
    "invalid_answers": (
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        "give one option for each question, in order",
    ),
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


class ArticleItemOut(ArticleBriefOut):
    # A version at my level is ready: opening it calls no model (Q43f).
    rewritten: bool
    # I have opened it before.
    read: bool


class ArticlesOut(BaseModel):
    articles: list[ArticleItemOut]
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
    feed_id: uuid.UUID | None = None,
) -> ArticlesOut:
    """Newest first, from the feeds this learner follows (or one of them)."""
    views = await feeds.list_articles(
        session,
        user.id,
        tenant.id,
        limit=limit,
        before=_parse_cursor(before) if before else None,
        feed_id=feed_id,
    )
    ids = [v.article.id for v in views]
    level = await versions.reading_level(session, user.id, get_rules())
    rewritten = set(
        await session.scalars(
            select(ArticleVersion.article_id).where(
                ArticleVersion.tenant_id == tenant.id,
                ArticleVersion.level == level,
                ArticleVersion.status == "ready",
                ArticleVersion.article_id.in_(ids),
            )
        )
    )
    read = set(
        await session.scalars(
            select(ReadingSession.article_id).where(
                ReadingSession.user_id == user.id, ReadingSession.article_id.in_(ids)
            )
        )
    )
    return ArticlesOut(
        articles=[
            ArticleItemOut.model_validate(
                {**_brief(v), "rewritten": v.article.id in rewritten, "read": v.article.id in read}
            )
            for v in views
        ],
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


class ResultOut(BaseModel):
    choice: int
    correct: bool
    # Sent only once answered: the right option and the sentence that shows it.
    answer: int
    evidence: str


class SessionOut(BaseModel):
    id: uuid.UUID
    # The original, always there to switch to (Q43g).
    article: ArticleOut
    level: str
    # My version (poll `GET /reading/versions/{id}` while generating); null when the
    # article is not rewritten for me, then `original_reason` says why (Q43e).
    version: VersionOut | None
    original_reason: str | None
    # The first answers, graded; null until answered.
    results: list[ResultOut] | None
    finished_at: datetime | None


def _result_out(r: sessions.Result) -> ResultOut:
    return ResultOut(choice=r.choice, correct=r.correct, answer=r.answer, evidence=r.evidence)


@router.post("/articles/{article_id}/session")
async def open_session(
    article_id: int,
    user: CurrentUser,
    tenant: CurrentTenant,
    session: SessionDep,
    worker: WorkerDep,
) -> SessionOut:
    """Start reading the article, or carry on: my version (started if needed), or the
    original when it is not rewritten for me. Once answered, the version stays."""
    rules = get_rules()
    try:
        view = await feeds.get_article(session, article_id, tenant.id)
    except FeedError as exc:
        _raise(exc)
    level = await versions.reading_level(session, user.id, rules)
    reason: str | None = None
    version_id = await sessions.answered_version(session, user.id, article_id)
    if version_id is None:
        try:
            version_id = await worker.request(user.id, tenant.id, article_id)
        except ReadingError as exc:
            reason = exc.code
        except FeedError as exc:
            _raise(exc)
    reading = await sessions.open_session(
        session, user.id, article_id, version_id=version_id, level=level, now=datetime.now(UTC)
    )
    version = (
        await session.get(ArticleVersion, reading.version_id, populate_existing=True)
        if reading.version_id is not None
        else None
    )
    return SessionOut(
        id=reading.id,
        article=ArticleOut.model_validate(
            {**_brief(view), "body": view.article.body, "site_url": view.feed.site_url}
        ),
        level=reading.level,
        version=_version_out(version, view, worker) if version is not None else None,
        original_reason=reason,
        results=(
            [_result_out(r) for r in sessions.results(version, reading.answers)]
            if version is not None and reading.answers is not None
            else None
        ),
        finished_at=reading.finished_at,
    )


class AnswersIn(BaseModel):
    # The option picked for each question, in order.
    choices: list[int] = Field(max_length=20)


class ResultsOut(BaseModel):
    results: list[ResultOut]
    # Whether these answers counted: only the first ones do (Q43b).
    counted: bool


@router.post("/sessions/{session_id}/answers")
async def answer_questions(
    session_id: uuid.UUID, body: AnswersIn, user: CurrentUser, session: SessionDep
) -> ResultsOut:
    """Grade the questions; the first answers move my reading ability, later ones
    only get the stored results back."""
    try:
        reading = await sessions.get_session(session, session_id, user.id, lock=True)
        counted = reading.answers is None
        results = await sessions.answer(
            session, reading, body.choices, rules=get_rules(), now=datetime.now(UTC)
        )
    except ReadingError as exc:
        _raise(exc)
    return ResultsOut(
        results=[_result_out(r) for r in results],
        counted=counted,
    )


class DueWordOut(BaseModel):
    word_id: int
    # As first used in the text, lowercase.
    form: str


class MarksOut(BaseModel):
    # Words of the text due for review today, as the review queue counts them (Q43d).
    due: list[DueWordOut]


async def _paragraphs(session: SessionDep, reading: ReadingSession, original: bool) -> list[str]:
    if not original and reading.version_id is not None:
        version = await session.get(ArticleVersion, reading.version_id)
        if version is not None and version.status == "ready":
            return version.paragraphs
    body = await session.scalar(select(Article.body).where(Article.id == reading.article_id))
    return body.split("\n\n") if body is not None else []


@router.get("/sessions/{session_id}/marks")
async def get_marks(
    session_id: uuid.UUID, user: CurrentUser, session: SessionDep, original: bool = False
) -> MarksOut:
    """Marks for the text shown: my version once ready, else (or with `original`) the
    original. The glossary comes with the version."""
    try:
        reading = await sessions.get_session(session, session_id, user.id)
    except ReadingError as exc:
        _raise(exc)
    paragraphs = await _paragraphs(session, reading, original)
    due = await sessions.due_words(
        session, user.id, paragraphs, rules=get_rules(), now=datetime.now(UTC)
    )
    return MarksOut(due=[DueWordOut.model_validate(d) for d in due])
