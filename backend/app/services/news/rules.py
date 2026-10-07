"""Which entries become articles, and under what license (ADR 0024 §1, §3; Q41a, Q41b, Q41d).

Built-in sources have their own rules, keyed by `BuiltinSource.key`; a learner's own
feed keeps everything readable, marked with the feed's license (`unknown`).
"""

import re
from collections.abc import Callable
from dataclasses import dataclass

from app.services.news.clean import count_words, html_to_text
from app.services.news.parse import ParsedEntry
from app.services.news.sources import GLOBAL_VOICES, NASA

# Fewer words than this and the feed gave a teaser, not the article (Q41d).
SUMMARY_ONLY_WORDS = 150
# NASA media advisories and event notices are a few short paragraphs (Q41b).
NASA_MIN_WORDS = 250


@dataclass(frozen=True)
class Kept:
    body: str
    word_count: int
    summary_only: bool
    license: str


@dataclass(frozen=True)
class Skipped:
    # Counted per run in logs; never shown to learners.
    reason: str


# --- NASA (Q41b) ---------------------------------------------------------------------

# The page template's header can carry another story's headline; content lists are
# teasers for other stories.
_NASA_SKIP_CLASSES = ("article-intro", "article-header", "hds-content-item", "hds-content-list")
# Reading time, image credits, release numbers ("2026-067").
_NASA_DROP = re.compile(r"^(\d+\s+min read|image credit\b.*|\d{4}-\d{3})$", re.IGNORECASE)
# Everything from here on is contacts, downloads or links to other stories.
_NASA_END = re.compile(
    r"^(-end-|(news\s+)?media\s+contacts?|keep exploring|related (links|terms|topics)"
    r"|discover (more|related)\b.*|downloads (&|and) related information"
    r"|related images (&|and) videos)$",
    re.IGNORECASE,
)


def _nasa(entry: ParsedEntry) -> str | Skipped:
    # Astronomy Picture of the Day: written by its two editors, images by others.
    if "/apod-" in entry.url or entry.title.upper().startswith("APOD") or "APOD" in entry.tags:
        return Skipped("apod")
    paragraphs: list[str] = []
    for paragraph in html_to_text(entry.html, skip_class_words=_NASA_SKIP_CLASSES).split("\n\n"):
        if _NASA_END.match(paragraph):
            break
        if not _NASA_DROP.match(paragraph):
            paragraphs.append(paragraph)
    body = "\n\n".join(paragraphs)
    if count_words(body) < NASA_MIN_WORDS:
        return Skipped("too_short")
    return body


# --- Global Voices (Q41a) ------------------------------------------------------------

# A partner's story republished with permission: its license is not Global Voices'
# CC BY. The notice is a paragraph of its own, opening with "This article / story...".
_NOTICE = re.compile(
    r"^(?:this|the following|an? (?:\w+ )?version of this)\s+"
    r"(?:article|story|post|piece|report|interview|essay)\b",
    re.IGNORECASE,
)
_REPUBLISHED = re.compile(
    r"\b(?:originally|first)\s+(?:published|appeared)\s+(?:by|in|on|at)\s+(?!global voices\b)"
    r"|\brepublished\s+(?:here|with|under)\b",
    re.IGNORECASE,
)


def _global_voices(entry: ParsedEntry) -> str | Skipped:
    body = html_to_text(entry.html)
    for paragraph in body.split("\n\n"):
        if _NOTICE.match(paragraph) and _REPUBLISHED.search(paragraph):
            return Skipped("republished")
    return body


_SOURCE_RULES: dict[str, Callable[[ParsedEntry], str | Skipped]] = {
    NASA: _nasa,
    GLOBAL_VOICES: _global_voices,
}


# A teaser's link to the full story.
_READ_MORE = re.compile(
    r"\s*(?:\[?(?:…|\.\.\.)\]?\s*)?(?:read more|continue reading|read the full \w+)\W*$",
    re.IGNORECASE,
)


def _tidy(body: str, title: str) -> str:
    """Drop a repeated title at the top and a "Read more" at the end."""
    paragraphs = body.split("\n\n")
    while paragraphs and paragraphs[0].casefold() == title.casefold():
        paragraphs.pop(0)
    if paragraphs:
        paragraphs[-1] = _READ_MORE.sub("", paragraphs[-1])
    return "\n\n".join(p for p in paragraphs if p)


def judge(entry: ParsedEntry, *, source: str | None, feed_license: str) -> Kept | Skipped:
    """`source`: the built-in source's key; None for a learner's own feed."""
    rule = _SOURCE_RULES.get(source) if source else None
    body = rule(entry) if rule else html_to_text(entry.html)
    if isinstance(body, Skipped):
        return body
    body = _tidy(body, entry.title)
    words = count_words(body)
    if words == 0:
        return Skipped("empty")
    summary_only = words < SUMMARY_ONLY_WORDS
    if summary_only and source:
        # Built-in sources carry full text; a teaser from one is not worth showing.
        return Skipped("too_short")
    return Kept(body=body, word_count=words, summary_only=summary_only, license=feed_license)
