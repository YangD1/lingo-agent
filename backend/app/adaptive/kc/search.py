"""Finding grammar KCs by name (ADR 0046 §1).

The tutor names a grammar point in its own words ("subject + verb word order", "现在完成时")
when the conversation's context gave it no id. Matching is plain word overlap with the
catalog's ids, names and descriptions: 119 hand-written entries need no embeddings, and
an unclear match goes back to the model as candidates to choose from.
"""

import re
from collections.abc import Collection
from dataclasses import dataclass

from app.adaptive.kc.catalog import GrammarCatalog, GrammarKC

# Words that say nothing about which grammar point is meant.
_STOPWORDS = frozenset(
    {
        "a", "an", "the", "and", "or", "of", "in", "on", "to", "for", "with", "vs",
        "grammar", "point", "rule", "rules", "use", "using", "usage", "english", "basic",
    }
)  # fmt: skip
_WORD = re.compile(r"[a-z]+")
_CJK = re.compile(r"[一-鿿]+")
# Matches in an id or a name count this much more than in the description.
_NAME_WEIGHT = 3
# A best match this many times the runner-up's score is taken as the one meant.
_CLEAR_MARGIN = 1.5


@dataclass(frozen=True)
class KCMatch:
    kc: GrammarKC
    score: float


def _stem(word: str) -> str:
    return word[:-1] if len(word) > 3 and word.endswith("s") and not word.endswith("ss") else word


def _words(text: str) -> set[str]:
    return {_stem(w) for w in _WORD.findall(text.lower()) if w not in _STOPWORDS}


def _bigrams(text: str) -> set[str]:
    grams: set[str] = set()
    for run in _CJK.findall(text):
        grams.update(run[i : i + 2] for i in range(max(len(run) - 1, 1)))
    return grams


def find_kcs(
    catalog: GrammarCatalog, topic: str, within: Collection[str] | None = None
) -> list[KCMatch]:
    """KCs matching `topic`, best first; only those in `within` when it is given."""
    query = topic.strip().lower()
    words, grams = _words(query), _bigrams(query)
    matches: list[KCMatch] = []
    for kc in catalog.kcs:
        if within is not None and kc.id not in within:
            continue
        if query in (kc.id, kc.id.removeprefix("g."), kc.name_en.lower(), kc.name_zh):
            return [KCMatch(kc, float("inf"))]
        named = _words(kc.id.replace("_", " ") + " " + kc.name_en)
        described = _words(kc.description)
        score = (
            _NAME_WEIGHT * len(words & named)
            + len((words - named) & described)
            + _NAME_WEIGHT * len(grams & _bigrams(kc.name_zh))
        )
        if score > 0:
            matches.append(KCMatch(kc, score))
    matches.sort(key=lambda m: -m.score)
    return matches


def is_clear(matches: list[KCMatch]) -> bool:
    """Whether the best match stands out enough to use without asking."""
    if not matches:
        return False
    return len(matches) == 1 or matches[0].score >= _CLEAR_MARGIN * matches[1].score
