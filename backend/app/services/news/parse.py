"""RSS / Atom bytes -> feed entries, before any source rules (ADR 0024)."""

import hashlib
import html
from dataclasses import dataclass
from datetime import UTC, datetime
from time import struct_time
from typing import Any

import feedparser

from app.services.news.clean import html_to_text, one_line
from app.services.news.fetch import FeedFetchError

# Entries looked at per fetch; feeds list newest first.
MAX_ENTRIES = 100
MAX_TAGS = 20
_GUID_LIMIT = 500


@dataclass(frozen=True)
class ParsedEntry:
    guid: str
    url: str
    title: str
    author: str | None
    published_at: datetime
    # The entry's body as HTML: its full content when the feed has it, else its summary.
    html: str
    tags: tuple[str, ...]


@dataclass(frozen=True)
class ParsedFeed:
    title: str | None
    site_url: str | None
    entries: tuple[ParsedEntry, ...]


def _date(value: struct_time | None, now: datetime) -> datetime:
    if value is None:
        return now
    # feedparser normalizes dates to UTC. A date in the future would sort above
    # everything for days; treat it as "now".
    return min(datetime(*value[:6], tzinfo=UTC), now)


def _as_html(detail: Any) -> str:
    value = str(detail.get("value") or "")
    if "html" in str(detail.get("type") or "html"):
        return value
    return html.escape(value)


def _title(entry: Any) -> str:
    detail = entry.get("title_detail") or {}
    value = str(entry.get("title") or "")
    if "html" in str(detail.get("type") or ""):
        value = html_to_text(value)
    # Some feeds escape twice ("&amp;amp;"); decode what is left.
    return one_line(html.unescape(value))[:500]


def _body(entry: Any) -> str:
    contents = [_as_html(c) for c in entry.get("content") or []]
    if contents:
        return max(contents, key=len)
    detail = entry.get("summary_detail")
    if detail:
        return _as_html(detail)
    return str(entry.get("summary") or "")


def _guid(entry: Any, url: str) -> str:
    guid = str(entry.get("id") or url)
    if len(guid) > _GUID_LIMIT:
        return "sha256:" + hashlib.sha256(guid.encode()).hexdigest()
    return guid


def _tags(entry: Any) -> tuple[str, ...]:
    terms = (one_line(str(t.get("term") or ""))[:100] for t in entry.get("tags") or [])
    return tuple(dict.fromkeys(t for t in terms if t))[:MAX_TAGS]


def parse_feed(content: bytes, *, now: datetime) -> ParsedFeed:
    """Raises FeedFetchError("not_a_feed") when `content` is not RSS or Atom."""
    parsed = feedparser.parse(content)
    if not parsed.get("version") and not parsed.entries:
        raise FeedFetchError("not_a_feed")
    entries = []
    for entry in parsed.entries[:MAX_ENTRIES]:
        url = str(entry.get("link") or "").strip()
        if not url.startswith(("http://", "https://")) or len(url) > 2000:
            continue  # nowhere to send the reader for the original
        author = one_line(html.unescape(str(entry.get("author") or "")))[:300]
        entries.append(
            ParsedEntry(
                guid=_guid(entry, url),
                url=url,
                title=_title(entry),
                author=author or None,
                published_at=_date(
                    entry.get("published_parsed") or entry.get("updated_parsed"), now
                ),
                html=_body(entry),
                tags=_tags(entry),
            )
        )
    feed = parsed.get("feed") or {}
    title = one_line(str(feed.get("title") or ""))[:300]
    site_url = str(feed.get("link") or "").strip()
    return ParsedFeed(
        title=title or None,
        site_url=site_url if site_url.startswith(("http://", "https://")) else None,
        entries=tuple(entries),
    )
