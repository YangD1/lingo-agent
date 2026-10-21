"""Import English senses from Simple English Wiktionary into `word_senses`:
`python -m app.services.vocab.import_simplewiktionary`.

ADR 0062: learner-style definitions with examples (CC BY-SA), up to MAX_SENSES per
word in page order, for words whose page title is spelt exactly like the `words` row.
The dump has no versioned address, so nothing is pinned: the file's date and sha256
are printed instead, and `--file` imports a local copy. The download is cached in
`data/simplewiktionary/` (gitignored); `--refresh` fetches it again. A run replaces
all of the source's rows in one transaction. Runs on the host (`make senses-import`).
"""

import argparse
import asyncio
import hashlib
import os
import sys
import time
from collections.abc import Mapping
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

import anyio
import httpx2
from sqlalchemy import delete, exists, func, select
from sqlalchemy.ext.asyncio import AsyncConnection

from app.db.models import Word, WordSense
from app.db.session import create_engine
from app.services.vocab.books import BOOKS, Book
from app.services.vocab.simplewiktionary import Sense, parse_page, read_pages
from app.settings import REPO_ROOT, get_settings

SOURCE = "simplewiktionary"
URL = (
    "https://dumps.wikimedia.org/simplewiktionary/latest/"
    "simplewiktionary-latest-pages-articles.xml.bz2"
)
CACHE_DIR = REPO_ROOT / "data" / "simplewiktionary"
MAX_SENSES = 8
MAX_EXAMPLES = 3
# Column widths in word_senses.
_LABEL_WIDTH, _NYM_WIDTH = 40, 100


class DownloadError(Exception):
    """The dump could not be fetched."""


def read_senses(path: Path, words: Mapping[str, int]) -> dict[int, tuple[str, list[Sense]]]:
    """Each word's page title and senses, for words the dump has a page for."""
    found: dict[int, tuple[str, list[Sense]]] = {}
    for title, text in read_pages(path):
        word_id = words.get(title)
        if word_id is None:
            continue
        senses = parse_page(title, text)
        if senses:
            found[word_id] = (title, senses[:MAX_SENSES])
    return found


def _fit(items: tuple[str, ...], width: int) -> list[str]:
    return [i for i in items if len(i) <= width]


async def load_senses(conn: AsyncConnection, found: Mapping[int, tuple[str, list[Sense]]]) -> int:
    """Replace the source's rows with `found`; does not commit. Returns the row count."""
    await conn.execute(delete(WordSense).where(WordSense.source == SOURCE))
    raw: Any = (await conn.get_raw_connection()).driver_connection
    count = 0
    columns = (
        "word_id, source, rank, pos, gloss, labels, examples, synonyms, antonyms, source_title"
    )
    async with raw.cursor() as cursor:
        async with cursor.copy(f"COPY word_senses ({columns}) FROM STDIN") as copy:
            for word_id, (title, senses) in sorted(found.items()):
                for rank, s in enumerate(senses):
                    await copy.write_row(
                        (
                            word_id,
                            SOURCE,
                            rank,
                            s.pos,
                            s.gloss,
                            _fit(s.labels, _LABEL_WIDTH),
                            list(s.examples[:MAX_EXAMPLES]),
                            _fit(s.synonyms, _NYM_WIDTH),
                            _fit(s.antonyms, _NYM_WIDTH),
                            title,
                        )
                    )
                    count += 1
    return count


async def coverage(conn: AsyncConnection) -> list[tuple[Book, int, int, int]]:
    """Per book: how many words, how many have a sense, how many an example."""
    has_sense = exists().where(WordSense.word_id == Word.id, WordSense.source == SOURCE)
    has_example = exists().where(
        WordSense.word_id == Word.id,
        WordSense.source == SOURCE,
        func.cardinality(WordSense.examples) > 0,
    )
    result = []
    for book in BOOKS:
        row = (
            await conn.execute(
                select(
                    func.count(), func.count().filter(has_sense), func.count().filter(has_example)
                ).where(book.words())
            )
        ).one()
        result.append((book, int(row[0]), int(row[1]), int(row[2])))
    return result


async def download(
    directory: Path,
    url: str = URL,
    *,
    refresh: bool = False,
    transport: httpx2.AsyncBaseTransport | None = None,
) -> Path:
    """Fetch the dump into `directory` unless it is there already; its modification
    time is set to the dump's date."""
    target = anyio.Path(directory / url.rsplit("/", 1)[-1])
    if await target.exists() and not refresh:
        return Path(target)
    await target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(".part")
    print(f"downloading {url}", file=sys.stderr)
    async with httpx2.AsyncClient(follow_redirects=True, timeout=60, transport=transport) as client:
        async with client.stream("GET", url) as response:
            if response.status_code != 200:
                raise DownloadError(f"HTTP {response.status_code} from {url}")
            async with await partial.open("wb") as f:
                async for chunk in response.aiter_bytes():
                    await f.write(chunk)
            modified = response.headers.get("last-modified")
    await partial.replace(target)
    if modified:
        stamp = parsedate_to_datetime(modified).timestamp()
        await asyncio.to_thread(os.utime, target, (stamp, stamp))
    return Path(target)


def describe(path: Path) -> str:
    """The dump's date and sha256, to record which version was imported."""
    digest = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(1 << 20):
            digest.update(chunk)
    date = time.strftime("%Y-%m-%d", time.gmtime(path.stat().st_mtime))
    return f"{path.name}  {date}  sha256 {digest.hexdigest()}"


async def import_file(
    database_url: str, path: Path
) -> tuple[int, list[tuple[Book, int, int, int]]]:
    """Import from the dump at `path`; returns rows written and coverage."""
    engine = create_engine(database_url)
    try:
        async with engine.begin() as conn:
            words = {w: i for i, w in await conn.execute(select(Word.id, Word.word))}
            found = await asyncio.to_thread(read_senses, path, words)
            count = await load_senses(conn, found)
            books = await coverage(conn)
    finally:
        await engine.dispose()
    return count, books


async def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--file", type=Path, help="import this local copy of the dump")
    parser.add_argument("--refresh", action="store_true", help="download the dump again")
    args = parser.parse_args(argv)
    started = time.monotonic()
    try:
        path = args.file or await download(CACHE_DIR, refresh=args.refresh)
    except (DownloadError, httpx2.HTTPError) as exc:
        print(f"download failed: {exc}", file=sys.stderr)
        print("pass --file with a local copy of the dump", file=sys.stderr)
        return 1
    print(await asyncio.to_thread(describe, path))
    count, books = await import_file(get_settings().database_url, path)
    print(f"wrote {count} senses in {time.monotonic() - started:.1f}s")
    for book, total, senses, examples in books:
        share = senses / total if total else 0
        with_examples = examples / total if total else 0
        print(
            f"  {book.id:<11} {senses:>5} / {total:<5} words have a sense ({share:.0%}),"
            f" {with_examples:.0%} an example"
        )
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
