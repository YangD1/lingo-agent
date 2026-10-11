"""Wrong meanings for listening cards (task 63, Q63c): hear a word, pick its meaning of four.

Picked by code, not a model: words of the learner's book about as common as the word
(so none stands out as rare), the same part of speech first, and none sharing a gloss
with the word or with each other.
"""

import random
import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from sqlalchemy import Integer, column, literal, select, values
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.selectable import LateralFromClause

from app.db.models import UserWordBook, Word
from app.services.vocab.books import get_book

CHOICES = 3
# Neighbours by frequency fetched on each side; the pick is made among them.
NEIGHBOURS = 15
# Terms of a gloss shown at most, and characters.
GLOSS_TERMS = 3
GLOSS_CHARS = 30
# Where an unranked word sits in frequency order: among the rare ones.
UNRANKED_FRQ = 20000
# A learner without a book draws from the Oxford 3000.
DEFAULT_BOOK = "oxford3000"

# "n. 殖民地, 移民队": a part of speech, then terms. Lines like "[医] 菌落" are a field's sense.
_POS = re.compile(r"^([a-z]+)\.\s*")
_FIELD = re.compile(r"^\[[^\]]*\]\s*")
_TERMS = re.compile(r"\s*[,\uff0c;\uff1b]\s*")  # half- and full-width , ;
_POS_GROUP = {"a": "adj", "adj": "adj", "vt": "v", "vi": "v", "v": "v", "pl": "n", "n": "n"}


@dataclass(frozen=True, slots=True)
class Gloss:
    # Shown on the choice, e.g. "n. 殖民地, 移民队".
    text: str
    # adj / v / n / adv / ...; "" when the line has none.
    pos: str
    terms: frozenset[str]


def gloss(translation: str) -> Gloss:
    """The first sense line of an ECDICT translation, cut to a few terms.

    Field senses ("[计] 资源") are skipped when there is a plain line.
    """
    lines = [line.strip() for line in translation.splitlines() if line.strip()]
    plain = [line for line in lines if not _FIELD.match(line)]
    line = (plain or lines or [""])[0]
    line = _FIELD.sub("", line)
    pos = ""
    if match := _POS.match(line):
        pos = _POS_GROUP.get(match.group(1), match.group(1))
        prefix, line = match.group(0).strip() + " ", line[match.end() :]
    else:
        prefix = ""
    terms = [term for term in _TERMS.split(line) if term][:GLOSS_TERMS]
    text = prefix + ", ".join(terms)
    if len(text) > GLOSS_CHARS:
        text = text[: GLOSS_CHARS - 1].rstrip(", ") + "…"
    return Gloss(text=text, pos=pos, terms=frozenset(terms))


def pick(answer: Gloss, candidates: Sequence[Gloss], rng: random.Random) -> list[str]:
    """Up to `CHOICES` wrong meanings for `answer`: the same part of speech first, none
    sharing a term with the answer or with another pick, in random order."""
    pool = list(candidates)
    rng.shuffle(pool)
    pool.sort(key=lambda g: g.pos != answer.pos)
    chosen: list[Gloss] = []
    taken = set(answer.terms)
    for candidate in pool:
        if len(chosen) == CHOICES:
            break
        if not candidate.terms or candidate.terms & taken or candidate.text == answer.text:
            continue
        chosen.append(candidate)
        taken |= candidate.terms
    rng.shuffle(chosen)
    return [g.text for g in chosen]


async def choices_for(
    session: AsyncSession,
    user_id: uuid.UUID,
    words: Sequence[Word],
    rng: random.Random | None = None,
) -> Mapping[int, list[str]]:
    """Wrong meanings for each of `words`, by word id; two queries (above and below).

    Fewer than `CHOICES` (even none) when the book has too few distinct neighbours; the
    client then shows the card the usual way.
    """
    if not words:
        return {}
    rng = rng or random.Random()
    plan = await session.get(UserWordBook, user_id)
    book = (get_book(plan.book_id) if plan else None) or get_book(DEFAULT_BOOK)
    assert book is not None

    targets = values(column("id", Integer), column("frq", Integer), name="targets").data(
        [(w.id, w.frq or w.bnc or UNRANKED_FRQ) for w in words]
    )
    t = targets.alias("t")

    def side(above: bool) -> LateralFromClause:
        order = Word.frq.asc() if above else Word.frq.desc()
        near = Word.frq >= t.c.frq if above else Word.frq < t.c.frq
        return (
            select(Word.translation)
            .where(book.words(), Word.frq.is_not(None), near, Word.id != t.c.id)
            .order_by(order)
            .limit(NEIGHBOURS)
            .lateral()
        )

    found: dict[int, list[str]] = {w.id: [] for w in words}
    for above in (True, False):
        near = side(above)
        rows = await session.execute(select(t.c.id, near.c.translation).join(near, literal(True)))
        for word_id, translation in rows.all():
            found[word_id].append(translation)
    return {w.id: pick(gloss(w.translation), [gloss(c) for c in found[w.id]], rng) for w in words}
