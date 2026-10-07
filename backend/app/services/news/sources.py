"""Built-in feeds (ADR 0024 §1).

Listed here in code and synced into `feeds` at startup, so the address or title can
change without a migration. Each one has its own rules for which entries to keep
(`app/services/news/rules.py`), keyed by `key`.
"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Feed


@dataclass(frozen=True)
class BuiltinSource:
    key: str
    url: str
    title: str
    site_url: str
    license: str


NASA = "nasa"
GLOBAL_VOICES = "global_voices"

BUILTIN_SOURCES: tuple[BuiltinSource, ...] = (
    # US government work, public domain; NASA's name and logos may not imply endorsement.
    BuiltinSource(
        key=NASA,
        url="https://www.nasa.gov/news-release/feed/",
        title="NASA News Releases",
        site_url="https://www.nasa.gov",
        license="public_domain",
    ),
    # Global Voices' own stories are CC BY 3.0; republished partner stories are skipped.
    BuiltinSource(
        key=GLOBAL_VOICES,
        url="https://globalvoices.org/feed/",
        title="Global Voices",
        site_url="https://globalvoices.org",
        license="cc_by",
    ),
)


async def sync_builtin_feeds(session: AsyncSession) -> None:
    """Make `feeds` match `BUILTIN_SOURCES`; caller commits.

    A built-in no longer listed is left alone: its articles may have been read, and it
    is simply never fetched again.
    """
    rows = {
        f.builtin_key: f
        for f in await session.scalars(select(Feed).where(Feed.builtin_key.is_not(None)))
    }
    for source in BUILTIN_SOURCES:
        feed = rows.get(source.key)
        if feed is None:
            session.add(
                Feed(
                    builtin_key=source.key,
                    url=source.url,
                    title=source.title,
                    site_url=source.site_url,
                    license=source.license,
                )
            )
            continue
        if feed.url != source.url:
            # A new address starts over: the old validators belong to the old one.
            feed.etag = feed.last_modified = None
            feed.next_fetch_at = None
        feed.url = source.url
        feed.title = source.title
        feed.site_url = source.site_url
        feed.license = source.license
