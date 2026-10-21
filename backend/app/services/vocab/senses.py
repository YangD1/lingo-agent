"""English senses for flashcards (ADR 0062), read from `word_senses`."""

from collections.abc import Iterable
from urllib.parse import quote

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import WordSense

# Where each source's page lives, for the "Source" link on the card.
_PAGES = {"simplewiktionary": "https://simple.wiktionary.org/wiki/{title}"}


def page(sense: WordSense) -> str | None:
    template = _PAGES.get(sense.source)
    title = quote(sense.source_title.replace(" ", "_"), safe="_()'")
    return template.format(title=title) if template else None


async def for_words(session: AsyncSession, word_ids: Iterable[int]) -> dict[int, list[WordSense]]:
    """Each word's senses in page order, in one query; words without any are absent."""
    ids = set(word_ids)
    if not ids:
        return {}
    rows = await session.scalars(
        select(WordSense)
        .where(WordSense.word_id.in_(ids))
        .order_by(WordSense.word_id, WordSense.source, WordSense.rank)
    )
    found: dict[int, list[WordSense]] = {}
    for row in rows:
        found.setdefault(row.word_id, []).append(row)
    return found
