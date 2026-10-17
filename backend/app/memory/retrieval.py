"""Picking conversation summaries without an embedding model, and without repeats
(ADR 0052 §4).

A learner has at most a few hundred summaries, so they are scored in process on every
turn: BM25 over word tokens (English words, Chinese character pairs), the
conversation title counting double, recent ones a little ahead. Picks that say nearly
the same thing as one already taken are skipped, so three "quizzed on subject + verb"
summaries don't fill all the places.
"""

import math
import re
from collections import Counter
from collections.abc import Hashable, Sequence
from dataclasses import dataclass
from datetime import datetime

# BM25 (the usual defaults).
K1 = 1.2
B = 0.75
TITLE_WEIGHT = 2
# Up to this share more for a summary from today, halving every RECENCY_HALF_LIFE_DAYS.
RECENCY_BONUS = 0.3
RECENCY_HALF_LIFE_DAYS = 14.0
# Word overlap (Jaccard) at which a summary repeats one already picked.
DUPLICATE_OVERLAP = 0.6

_WORD = re.compile(r"[a-z0-9]+(?:'[a-z]+)?")
_HAN = re.compile(r"[㐀-䶿一-鿿豈-﫿]+")


def tokens(text: str) -> list[str]:
    """English words and numbers, lowercased; each run of Chinese characters as its
    overlapping pairs (a single character stays one token)."""
    text = text.lower()
    found = _WORD.findall(text)
    for run in _HAN.findall(text):
        found.extend([run] if len(run) == 1 else [run[i : i + 2] for i in range(len(run) - 1)])
    return found


@dataclass(frozen=True)
class Candidate[K: Hashable]:
    key: K
    text: str
    title: str
    updated_at: datetime


def bm25(query: Sequence[str], docs: Sequence[Sequence[str]]) -> list[float]:
    """One score per doc; 0 for a doc sharing no token with the query."""
    if not docs:
        return []
    average = sum(len(d) for d in docs) / len(docs) or 1.0
    containing = Counter(t for d in docs for t in set(d))
    terms = set(query)
    scores = []
    for doc in docs:
        counts = Counter(doc)
        score = 0.0
        for term in terms:
            tf = counts.get(term, 0)
            if not tf:
                continue
            n = containing[term]
            idf = math.log(1 + (len(docs) - n + 0.5) / (n + 0.5))
            score += idf * tf * (K1 + 1) / (tf + K1 * (1 - B + B * len(doc) / average))
        scores.append(score)
    return scores


def overlap(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a or b else 1.0


def pick[K: Hashable](
    query: str,
    candidates: Sequence[Candidate[K]],
    limit: int,
    *,
    now: datetime,
    first: Sequence[K] = (),
) -> list[K]:
    """Up to `limit` keys: `first` (e.g. nearest by embedding) in its order, then by
    BM25 against `query` when `first` is empty, then the newest; repeats skipped."""
    by_key = {c.key: c for c in candidates}
    words = {c.key: set(tokens(c.text)) for c in candidates}
    order: list[K] = [k for k in first if k in by_key]
    if not order and query.strip():
        docs = [tokens(c.text) + tokens(c.title) * TITLE_WEIGHT for c in candidates]
        scored = [
            (score * _recency(c.updated_at, now), c)
            for score, c in zip(bm25(tokens(query), docs), candidates, strict=True)
            if score > 0
        ]
        scored.sort(key=lambda sc: (-sc[0], -sc[1].updated_at.timestamp()))
        order = [c.key for _, c in scored]
    order += [c.key for c in sorted(candidates, key=lambda c: c.updated_at, reverse=True)]
    picked: list[K] = []
    for key in dict.fromkeys(order):
        if any(overlap(words[key], words[p]) >= DUPLICATE_OVERLAP for p in picked):
            continue
        picked.append(key)
        if len(picked) == limit:
            break
    return picked


def _recency(updated_at: datetime, now: datetime) -> float:
    days = max((now - updated_at).total_seconds() / 86400, 0.0)
    return 1 + RECENCY_BONUS * math.pow(0.5, days / RECENCY_HALF_LIFE_DAYS)
