"""Graded versions of articles: which level a learner reads at, and storing a rewrite
(ADR 0024 §5, Q42a, Q42c, Q42i)."""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import cast

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.adaptive.kc.catalog import CefrLevel
from app.adaptive.rules import Rules
from app.agents.reading_graph import RewriteResult
from app.db.models import REWRITABLE_LICENSES, Article, ArticleVersion
from app.memory.service import get_profile
from app.services.news.clean import count_words
from app.services.reading import glossary


class ReadingError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


async def reading_level(session: AsyncSession, user_id: uuid.UUID, rules: Rules) -> CefrLevel:
    """The learner's placement level, else practice.default_level (Q42a)."""
    profile = await get_profile(session, user_id)
    level = profile.cefr_level if profile is not None else None
    return cast(CefrLevel, level or rules.practice.default_level)


def check_rewritable(article: Article, level: CefrLevel, rules: Rules) -> None:
    """Raise `ReadingError` when this article is not rewritten for this level: only a
    summary (Q41d), a license that allows no adaptation (Q42i), or a learner past the
    last level, who reads the original (Q42a)."""
    if article.summary_only:
        raise ReadingError("summary_only")
    if article.license not in REWRITABLE_LICENSES:
        raise ReadingError("not_rewritable")
    if level not in rules.reading.levels:
        raise ReadingError("level_above")


@dataclass(frozen=True, slots=True)
class Source:
    title: str
    body: str


async def load_source(session: AsyncSession, version_id: uuid.UUID) -> tuple[Source, CefrLevel]:
    row = (
        await session.execute(
            select(Article.title, Article.body, ArticleVersion.level)
            .join(ArticleVersion, ArticleVersion.article_id == Article.id)
            .where(ArticleVersion.id == version_id)
        )
    ).one()
    return Source(row.title, row.body), cast(CefrLevel, row.level)


async def save_result(
    session: AsyncSession,
    version_id: uuid.UUID,
    result: RewriteResult,
    *,
    level: CefrLevel,
    rules: Rules,
    now: datetime,
) -> None:
    """Fill in a `generating` version (or fail it); does not commit."""
    finished = ArticleVersion.id == version_id, ArticleVersion.status == "generating"
    if result.error_code is not None:
        await session.execute(
            update(ArticleVersion)
            .where(*finished)
            .values(status="failed", error_code=result.error_code, finished_at=now)
        )
        return
    words = await glossary.build(
        session,
        result.paragraphs,
        cut=rules.reading.glossary_rank[level],
        limit=rules.reading.glossary_max,
    )
    await session.execute(
        update(ArticleVersion)
        .where(*finished)
        .values(
            status="ready",
            error_code=None,
            title=result.title[:500],
            paragraphs=result.paragraphs,
            word_count=count_words("\n\n".join(result.paragraphs)),
            glossary=words.words,
            above_level_share=words.above_level_share,
            questions=[q.stored() for q in result.questions],
            rejected=result.rejected,
            model=result.model,
            critic_model=result.critic_model,
            finished_at=now,
        )
    )
