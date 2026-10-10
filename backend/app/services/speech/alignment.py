"""Comparing a speech-to-text transcript with the sentence the learner read: the rough
shadowing result when no pronunciation assessment is configured (ADR 0028 §5).

Word level only and no scores: it shows which words were left out, heard as another
word, or added. A transcript can be wrong in its own right, so the UI says this is a
rough result, and it never counts as evidence (ADR 0028 §6).

Words are compared after normalizing case, punctuation, curly apostrophes, common
contractions and small numbers, so "Don't" matches "do not" and "5" matches "five".
"""

import re
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict

type WordStatus = Literal["none", "omission", "insertion", "substitution"]


class AlignedWord(BaseModel):
    model_config = ConfigDict(frozen=True)

    # The sentence's word as written; for an insertion, the word heard.
    word: str
    status: WordStatus
    # What was heard instead, for a substitution.
    heard: str | None = None


class RoughResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    words: tuple[AlignedWord, ...]
    recognized_text: str
    # Words of the sentence heard as written, out of all of them.
    matched: int
    total: int


# Curly and modifier apostrophes, built from code points: ruff flags the literals.
_CURLY = "".join(map(chr, (0x2019, 0x2018, 0x02BC)))
_APOSTROPHES = str.maketrans(dict.fromkeys(_CURLY, "'"))
_WORD = re.compile(rf"[A-Za-z0-9]+(?:['{_CURLY}][A-Za-z]+)*")
# Contractions whose expansion is unambiguous; "'d" and "'s" are not ("had"/"would",
# "is"/"has"/possessive), so those stay as written.
_CONTRACTIONS = {
    "won't": ("will", "not"),
    "can't": ("can", "not"),
    "shan't": ("shall", "not"),
    "i'm": ("i", "am"),
}
_SUFFIXES = (("n't", ("not",)), ("'re", ("are",)), ("'ll", ("will",)), ("'ve", ("have",)))
_NUMBERS = (
    "zero one two three four five six seven eight nine ten eleven twelve thirteen "
    "fourteen fifteen sixteen seventeen eighteen nineteen twenty"
).split()


def _keys(word: str) -> tuple[str, ...]:
    """The normalized tokens one written word stands for."""
    lowered = word.translate(_APOSTROPHES).lower()
    if lowered in _CONTRACTIONS:
        return _CONTRACTIONS[lowered]
    for suffix, tail in _SUFFIXES:
        if lowered.endswith(suffix) and len(lowered) > len(suffix):
            return (lowered[: -len(suffix)], *tail)
    if lowered.isdigit() and int(lowered) < len(_NUMBERS):
        return (_NUMBERS[int(lowered)],)
    return (lowered,)


@dataclass(frozen=True)
class _Token:
    key: str
    word: int  # index of the written word it came from


def _tokens(words: list[str]) -> list[_Token]:
    return [_Token(key, i) for i, word in enumerate(words) for key in _keys(word)]


def words_of(text: str) -> list[str]:
    return _WORD.findall(text)


def _align(ref: list[_Token], hyp: list[_Token]) -> list[tuple[int | None, int | None]]:
    """Levenshtein over tokens; pairs of (ref index, hyp index), None for a gap."""
    n, m = len(ref), len(hyp)
    cost = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        cost[i][0] = i
    for j in range(m + 1):
        cost[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            same = ref[i - 1].key == hyp[j - 1].key
            cost[i][j] = min(
                cost[i - 1][j - 1] + (0 if same else 1),
                cost[i - 1][j] + 1,
                cost[i][j - 1] + 1,
            )
    pairs: list[tuple[int | None, int | None]] = []
    i, j = n, m
    while i or j:
        if i and j and cost[i][j] == cost[i - 1][j - 1] + (ref[i - 1].key != hyp[j - 1].key):
            pairs.append((i - 1, j - 1))
            i, j = i - 1, j - 1
        elif i and cost[i][j] == cost[i - 1][j] + 1:
            pairs.append((i - 1, None))
            i -= 1
        else:
            pairs.append((None, j - 1))
            j -= 1
    pairs.reverse()
    return pairs


def compare(reference_text: str, transcript: str) -> RoughResult:
    ref_words, hyp_words = words_of(reference_text), words_of(transcript)
    ref, hyp = _tokens(ref_words), _tokens(hyp_words)
    pairs = _align(ref, hyp)

    # Per written word of the sentence: how its tokens fared, and what was heard for it.
    matched_tokens = [0] * len(ref_words)
    token_count = [0] * len(ref_words)
    heard: list[list[str]] = [[] for _ in ref_words]
    for t in ref:
        token_count[t.word] += 1
    # Words heard but matching nothing, placed after the sentence word they follow.
    inserted: dict[int, list[str]] = {}
    last_ref_word = -1
    seen_hyp_words: set[int] = set()
    for r, h in pairs:
        if r is not None:
            last_ref_word = ref[r].word
        if r is not None and h is not None:
            if ref[r].key == hyp[h].key:
                matched_tokens[ref[r].word] += 1
            if hyp[h].word not in seen_hyp_words:
                heard[ref[r].word].append(hyp_words[hyp[h].word])
        elif h is not None and hyp[h].word not in seen_hyp_words:
            inserted.setdefault(last_ref_word, []).append(hyp_words[hyp[h].word])
        if h is not None:
            seen_hyp_words.add(hyp[h].word)

    words: list[AlignedWord] = [
        AlignedWord(word=w, status="insertion") for w in inserted.get(-1, [])
    ]
    for i, written in enumerate(ref_words):
        if matched_tokens[i] == token_count[i]:
            words.append(AlignedWord(word=written, status="none"))
        elif heard[i]:
            words.append(AlignedWord(word=written, status="substitution", heard=" ".join(heard[i])))
        else:
            words.append(AlignedWord(word=written, status="omission"))
        words += [AlignedWord(word=w, status="insertion") for w in inserted.get(i, [])]
    return RoughResult(
        words=tuple(words),
        recognized_text=transcript.strip(),
        matched=sum(1 for w in words if w.status == "none"),
        total=len(ref_words),
    )
