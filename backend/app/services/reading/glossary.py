"""The glossary of a rewritten article: its words past the reader's level (Q42c).

Worked out in code, not asked of the model, so the same text always gives the same
list: each word of the rewrite is looked up in the lexicon (an inflected form through
ECDICT's `exchange`, "went" -> "go"), and a word whose frequency rank is past the
level's cut makes the list. Names are left out: a word only ever written with a capital
letter, except at the start of a sentence, is taken for one.
"""

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Word

_TOKEN = re.compile(r"[A-Za-z]+(?:['\u2019-][A-Za-z]+)*")
# A sentence starts at the beginning of a paragraph or after . ! ? and any closing
# quotes or brackets.
_SENTENCE_END = re.compile(r"[.!?][\"'\u201d\u2019)\]]*\s*$")


@dataclass(frozen=True, slots=True)
class Entry:
    word_id: int
    word: str
    # Lower is more frequent; None when the lexicon has no rank (a rare word).
    rank: int | None


@dataclass(frozen=True, slots=True)
class Glossary:
    # [{"word": lemma, "word_id": int, "form": as first used, lowercase}].
    words: list[dict[str, Any]]
    # Share of the text's lexicon words (counted each time used) past the cut; None
    # when the text has none.
    above_level_share: float | None


def tokens(paragraphs: Sequence[str]) -> list[tuple[str, bool]]:
    """Each word, lowercase, and whether it could be a common word: written in lower
    case, or capitalized only at the start of a sentence."""
    found: list[tuple[str, bool]] = []
    for paragraph in paragraphs:
        for match in _TOKEN.finditer(paragraph):
            text = match.group().replace("\u2019", "'")
            before = paragraph[: match.start()]
            starts_sentence = not before.strip() or bool(_SENTENCE_END.search(before))
            found.append((text.lower(), text[0].islower() or starts_sentence))
    return found


def _past(entry: Entry, cut: int) -> bool:
    return entry.rank is None or entry.rank > cut


def pick(
    paragraphs: Sequence[str], entries: Mapping[str, Entry], *, cut: int, limit: int
) -> Glossary:
    """`entries`: the lexicon entry for each lowercase form, as `load_entries` gives."""
    seen = tokens(paragraphs)
    names = {form for form, _ in seen} - {form for form, common in seen if common}
    words: list[dict[str, Any]] = []
    listed: set[int] = set()
    known = past = 0
    for form, _ in seen:
        entry = entries.get(form)
        if entry is None or form in names:
            continue
        known += 1
        if not _past(entry, cut):
            continue
        past += 1
        if entry.word_id not in listed and len(words) < limit:
            listed.add(entry.word_id)
            words.append({"word": entry.word, "word_id": entry.word_id, "form": form})
    return Glossary(words, past / known if known else None)


def _rank(frq: int | None, bnc: int | None) -> int | None:
    return min((r for r in (frq, bnc) if r is not None), default=None)


async def load_entries(session: AsyncSession, forms: Iterable[str]) -> dict[str, Entry]:
    """The lexicon entry for each form: the word itself (any case), else the lemma
    whose `exchange` lists it as an inflection. Ties go to the more frequent word, as
    in `vocab.mine.lookup`. One query, however many forms."""
    wanted = sorted({f.lower() for f in forms if f})
    if not wanted:
        return {}
    pattern = "|".join(re.escape(f) for f in wanted)
    rows = await session.execute(
        select(Word.id, Word.word, Word.exchange, Word.frq, Word.bnc).where(
            or_(
                func.lower(Word.word).in_(wanted),
                Word.exchange.regexp_match(f"(^|/)[^01/]:({pattern})(/|$)", flags="i"),
            )
        )
    )
    exact: dict[str, Entry] = {}
    inflected: dict[str, Entry] = {}
    wanted_set = set(wanted)

    def better(current: Entry | None, new: Entry) -> bool:
        if current is None:
            return True
        return (new.rank is not None, -(new.rank or 0)) > (
            current.rank is not None,
            -(current.rank or 0),
        )

    for word_id, word, exchange, frq, bnc in rows:
        entry = Entry(word_id, word, _rank(frq, bnc))
        lowered = word.lower()
        if lowered in wanted_set and better(exact.get(lowered), entry):
            exact[lowered] = entry
        for part in (exchange or "").split("/"):
            kind, _, form = part.partition(":")
            form = form.lower()
            if kind not in ("0", "1") and form in wanted_set and better(inflected.get(form), entry):
                inflected[form] = entry
    return {form: exact.get(form) or inflected[form] for form in exact.keys() | inflected.keys()}


async def build(
    session: AsyncSession, paragraphs: Sequence[str], *, cut: int, limit: int
) -> Glossary:
    entries = await load_entries(session, (form for form, _ in tokens(paragraphs)))
    return pick(paragraphs, entries, cut=cut, limit=limit)
