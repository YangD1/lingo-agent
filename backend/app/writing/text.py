"""Counting and splitting a learner's writing, in code (P2 plan §4.2).

The review model is given the text as numbered sentences and answers by number, so
its corrections are matched to the learner's sentences without trusting it to copy
them back.
"""

import re
from dataclasses import dataclass

# Q38f: shorter is not much to review; longer costs too much for one call.
MIN_WORDS = 20
MAX_WORDS = 800
MAX_CHARS = 6000

_WORD = re.compile(r"[A-Za-z]+(?:['\u2019-][A-Za-z]+)*")
# A sentence ends at . ! ? (with closing quotes or brackets) before whitespace.
_SENTENCE_END = re.compile(r"(?:(?<=[.!?])|(?<=[.!?][\"'\u201d\u2019)\]]))\s+")


def word_count(text: str) -> int:
    """English words: runs of letters, with inner apostrophes and hyphens."""
    return len(_WORD.findall(text))


@dataclass(frozen=True, slots=True)
class Sentence:
    index: int
    paragraph: int
    text: str


def sentences(text: str) -> list[Sentence]:
    """The text's sentences in order, numbered from 0, with their paragraph. A
    paragraph is a block separated by blank lines; a line break alone does not end a
    sentence or a paragraph."""
    out: list[Sentence] = []
    paragraphs = [p for p in re.split(r"\n\s*\n", text.strip()) if p.strip()]
    for number, paragraph in enumerate(paragraphs):
        flat = re.sub(r"\s+", " ", paragraph).strip()
        for part in _SENTENCE_END.split(flat):
            if part.strip():
                out.append(Sentence(len(out), number, part.strip()))
    return out
