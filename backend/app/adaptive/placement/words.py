"""Real words for the vocabulary-size test (P1 plan §6.2, Q15a).

The test asks about lemmas, sampled by contemporary frequency rank (ECDICT `frq`). The
rank list also holds forms of other words, names and fragments, which are left out:

- inflections: `exchange` names another word as the lemma (`0:go` on "went") and the
  word has no forms of its own. ECDICT also lists some real lemmas as forms ("number"
  as a comparative of "numb", "better" of "good"); those have their own plural or
  tenses and stay in.
- anything but lowercase letters: names and adjectives of nationality ("Welsh"),
  abbreviations ("LSD"), contractions ("n't").
- vulgar words and slurs, by exact match (substrings would drop "cockpit", "Essex").

Each band's count of words kept is what the size estimate counts (`vocab_size`).
"""

import random
import re
from collections.abc import Collection, Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adaptive.placement.vocab_size import Band, band_of, bands
from app.adaptive.rules import PlacementVocabRules
from app.db.models import Word

_LOWERCASE = re.compile(r"^[a-z]+$")
# exchange keys for a word's own forms: past, past participle, -ing, 3rd person,
# comparative, superlative, plural. "0" is the lemma, "1" the kinds of form it is.
_FORM_KEYS = frozenset("pdi3rts")

_VULGAR = frozenset({
    "arse", "asshole", "bastard", "bitch", "bollocks", "boob", "boobs", "bugger", "chink",
    "cock", "crap", "cunt", "damn", "dick", "dyke", "erotic", "fag", "faggot", "fuck",
    "fucker", "fucking", "horny", "kike", "masturbate", "nigga", "nigger", "orgasm", "penis",
    "piss", "porn", "porno", "prick", "pussy", "queer", "rape", "rapist", "retard", "sexy",
    "shit", "shitty", "slut", "spic", "tits", "twat", "vagina", "wank", "whore",
})  # fmt: skip


def is_testable(word: str, exchange: str | None) -> bool:
    """Whether a dictionary entry can be asked about in the vocabulary test."""
    if not _LOWERCASE.match(word) or word in _VULGAR:
        return False
    lemma, own_forms = None, False
    for part in (exchange or "").split("/"):
        key, _, value = part.partition(":")
        if key == "0":
            lemma = value
        elif key in _FORM_KEYS and value and value != word:
            own_forms = True
    return lemma is None or lemma == word or own_forms


@dataclass(frozen=True, slots=True)
class PoolWord:
    id: int
    word: str
    rank: int


@dataclass(frozen=True, slots=True)
class WordPool:
    """Testable words of each band, in rank order."""

    bands: tuple[tuple[PoolWord, ...], ...]

    @property
    def band_words(self) -> list[int]:
        return [len(words) for words in self.bands]

    def pick(self, band: Band, used: Collection[int], rng: random.Random) -> PoolWord | None:
        """A random word of the band not yet used, or None when there is none left."""
        left = [w for w in self.bands[band.index] if w.id not in used]
        return rng.choice(left) if left else None

    def pick_nearest(
        self, order: Sequence[Band], used: Collection[int], rng: random.Random
    ) -> PoolWord | None:
        """A word from the first band in `order` that has one left."""
        for band in order:
            word = self.pick(band, used, rng)
            if word is not None:
                return word
        return None


def build_pool(
    rows: Sequence[tuple[int, str, int, str | None]], rules: PlacementVocabRules
) -> WordPool:
    """Pool from (id, word, frq, exchange) rows; rows out of range or untestable are dropped."""
    grouped: list[list[PoolWord]] = [[] for _ in bands(rules)]
    for word_id, word, rank, exchange in rows:
        index = band_of(rank, rules)
        if index is not None and is_testable(word, exchange):
            grouped[index].append(PoolWord(word_id, word, rank))
    return WordPool(tuple(tuple(sorted(g, key=lambda w: (w.rank, w.id))) for g in grouped))


async def load_pool(session: AsyncSession, rules: PlacementVocabRules) -> WordPool:
    rows = await session.execute(
        select(Word.id, Word.word, Word.frq, Word.exchange).where(
            Word.frq.between(1, rules.max_rank)
        )
    )
    return build_pool([(r.id, r.word, r.frq, r.exchange) for r in rows], rules)
