"""reading_coach's article (Q43h, Q43i).

A conversation opened from the reading page is about one article: each turn the
coach is given its text, the version at the learner's level when one is ready, else
the original's first `MAX_ORIGINAL_WORDS` words. The text is data, not instructions:
the prompt marks it off and says so.

Bound at the API layer to the learner, tenant and article, like the tutor's tools.
"""

import uuid
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.adaptive.kc.catalog import CefrLevel
from app.adaptive.rules import get_rules
from app.db.models import ArticleVersion
from app.prompts import load_prompt
from app.services.news import feeds
from app.services.news.clean import count_words
from app.services.news.feeds import FeedError
from app.services.reading.versions import reading_level

# A long original is cut here: enough for questions about it, within a chat call.
MAX_ORIGINAL_WORDS = 1500


@dataclass(frozen=True)
class ReadingFocus:
    article_id: int
    title: str
    paragraphs: list[str]
    # The version's level; None for the original.
    level: CefrLevel | None
    # Words sent to the coach.
    words: int
    # The original was too long and only its beginning was sent.
    cut: bool = False


class ReadingSource(Protocol):
    async def load(self) -> ReadingFocus | None:
        """None when the learner can no longer see the article."""
        ...


class DatabaseReading:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        *,
        user_id: uuid.UUID,
        tenant_id: uuid.UUID,
        article_id: int,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._user_id = user_id
        self._tenant_id = tenant_id
        self._article_id = article_id

    async def load(self) -> ReadingFocus | None:
        async with self._sessionmaker() as session:
            try:
                view = await feeds.get_article(session, self._article_id, self._tenant_id)
            except FeedError:
                return None
            level = await reading_level(session, self._user_id, get_rules())
            version = await session.scalar(
                select(ArticleVersion).where(
                    ArticleVersion.tenant_id == self._tenant_id,
                    ArticleVersion.article_id == self._article_id,
                    ArticleVersion.level == level,
                    ArticleVersion.status == "ready",
                )
            )
        if version is not None:
            return ReadingFocus(
                self._article_id,
                version.title or view.article.title,
                version.paragraphs,
                level,
                version.word_count,
            )
        whole = view.article.body.split("\n\n")
        paragraphs = beginning(whole, MAX_ORIGINAL_WORDS)
        return ReadingFocus(
            self._article_id,
            view.article.title,
            paragraphs,
            None,
            sum(count_words(p) for p in paragraphs),
            cut=len(paragraphs) < len(whole),
        )


def beginning(paragraphs: list[str], limit: int) -> list[str]:
    """Whole paragraphs up to `limit` words; a paragraph past it is left out, unless it
    is the first."""
    kept: list[str] = []
    words = 0
    for paragraph in paragraphs:
        n = count_words(paragraph)
        if kept and words + n > limit:
            break
        kept.append(paragraph)
        words += n
    return kept


def render_reading(focus: ReadingFocus | None) -> str:
    """The coach's guidance for this turn."""
    if focus is None:
        return load_prompt("reading_unavailable")
    note = (
        f", as rewritten for their level ({focus.level})"
        if focus.level is not None
        else " (the original text" + (", only its beginning" if focus.cut else "") + ")"
    )
    # replace, not format: the article may contain braces.
    return (
        load_prompt("reading_coach")
        .replace("{version_note}", note)
        .replace("{title}", focus.title.replace('"', "'"))
        .replace("{article}", "\n\n".join(focus.paragraphs))
    )
