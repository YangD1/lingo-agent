"""Real example sentences for flashcards (ADR 0020), read from `word_sentences`."""

from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import WordSentence

# Where each source's sentence page lives, for the "Source" link on the card.
_PAGES = {"tatoeba": "https://tatoeba.org/sentences/show/{id}"}


def page(sentence: WordSentence) -> str | None:
    template = _PAGES.get(sentence.source)
    return template.format(id=sentence.source_id) if template else None


async def for_words(
    session: AsyncSession, word_ids: Iterable[int]
) -> dict[int, list[WordSentence]]:
    """Each word's sentences, best first, in one query; words without any are absent."""
    ids = set(word_ids)
    if not ids:
        return {}
    rows = await session.scalars(
        select(WordSentence)
        .where(WordSentence.word_id.in_(ids))
        .order_by(WordSentence.word_id, WordSentence.source, WordSentence.rank)
    )
    found: dict[int, list[WordSentence]] = {}
    for row in rows:
        found.setdefault(row.word_id, []).append(row)
    return found
