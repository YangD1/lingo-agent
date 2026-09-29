"""Import the ECDICT subset into `words`: `python -m app.services.vocab.import_ecdict`.

ADR 0011: ECDICT (MIT) has ~770k entries, mostly phrases and rare words. Kept are the
words on an exam list, in the Oxford 3000, with Collins stars, or ranked in the top
30,000 by BNC or contemporary frequency. The CSV is read line by line, never whole,
and loaded with COPY, then upserted by word, so running it again is harmless. Words are
never deleted: learners' cards point at them.

The download is pinned to one ECDICT commit and checked against its sha256; it is
cached in `data/` (gitignored). `--csv` imports a local copy instead. It runs on the
host (`make vocab-import`), where the network and any proxy are available.
"""

import argparse
import asyncio
import csv
import hashlib
import sys
import time
from collections.abc import Iterable, Iterator
from dataclasses import astuple, dataclass
from pathlib import Path
from typing import Any

import anyio
import httpx2
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.db.session import create_engine
from app.settings import REPO_ROOT, get_settings

ECDICT_COMMIT = "bc015ed2e24a7abef49fc6dbbb7fe32c1dadaf8b"  # 2025-03-28
DEFAULT_URL = f"https://raw.githubusercontent.com/skywind3000/ECDICT/{ECDICT_COMMIT}/ecdict.csv"
SHA256 = "1a6947e04785db63613a92e14903cdae7954f7e84860b10e68e5c7cbb3f9c3cf"
CACHE_PATH = REPO_ROOT / "data" / "ecdict.csv"

EXAM_TAGS = frozenset({"zk", "gk", "cet4", "cet6", "ky", "toefl", "ielts", "gre"})
TOP_RANK = 30_000

COLUMNS = (
    "word",
    "phonetic",
    "translation",
    "definition",
    "collins",
    "oxford",
    "tags",
    "bnc",
    "frq",
    "exchange",
)


class DownloadError(Exception):
    """The download failed or does not match the pinned file."""


@dataclass(frozen=True, slots=True)
class WordRow:
    word: str
    phonetic: str | None
    translation: str
    definition: str | None
    collins: int
    oxford: bool
    tags: list[str]
    bnc: int | None
    frq: int | None
    exchange: str | None


def _rank(value: str) -> int | None:
    """ECDICT writes 0 or nothing for "not ranked"."""
    return int(value) if value.strip() and int(value) > 0 else None


def _text(value: str) -> str | None:
    # ECDICT escapes line breaks inside a field as a literal backslash-n.
    value = value.replace("\\n", "\n").strip()
    return value or None


def to_row(record: dict[str, str]) -> WordRow | None:
    """The entry as a `words` row, or None when it is outside the subset."""
    word = record["word"].strip()
    translation = _text(record["translation"])
    if not word or translation is None or len(word) > 100:
        return None
    tags = sorted(set(record["tag"].split()) & EXAM_TAGS)
    oxford = record["oxford"].strip() == "1"
    collins = int(record["collins"] or 0)
    bnc, frq = _rank(record["bnc"]), _rank(record["frq"])
    ranked = any(r is not None and r <= TOP_RANK for r in (bnc, frq))
    if not (tags or oxford or collins > 0 or ranked):
        return None
    return WordRow(
        word=word,
        phonetic=_text(record["phonetic"]),
        translation=translation,
        definition=_text(record["definition"]),
        collins=collins,
        oxford=oxford,
        tags=tags,
        bnc=bnc,
        frq=frq,
        exchange=_text(record["exchange"]),
    )


@dataclass
class Stats:
    read: int = 0
    kept: int = 0


def read_subset(lines: Iterable[str], stats: Stats) -> Iterator[WordRow]:
    """Stream the kept rows of an ECDICT CSV; later duplicates of a word are dropped."""
    seen: set[str] = set()
    for record in csv.DictReader(lines):
        stats.read += 1
        row = to_row(record)
        if row is None or row.word in seen:
            continue
        seen.add(row.word)
        stats.kept += 1
        yield row


async def load_words(conn: AsyncConnection, rows: Iterable[WordRow]) -> int:
    """COPY the rows into a temp table and upsert them into `words`; does not commit.

    Returns how many rows were inserted or changed.
    """
    columns = ", ".join(COLUMNS)
    # Column types only: no id sequence to advance, no constraints until the upsert.
    await conn.execute(
        text(
            f"CREATE TEMP TABLE words_import ON COMMIT DROP"
            f" AS SELECT {columns} FROM words WITH NO DATA"
        )
    )
    raw: Any = (await conn.get_raw_connection()).driver_connection
    async with raw.cursor() as cursor:
        async with cursor.copy(f"COPY words_import ({columns}) FROM STDIN") as copy:
            for row in rows:
                await copy.write_row(astuple(row))
    updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in COLUMNS if c != "word")
    changed = " OR ".join(f"words.{c} IS DISTINCT FROM EXCLUDED.{c}" for c in COLUMNS)
    result = await conn.execute(
        text(
            f"INSERT INTO words ({columns}) SELECT {columns} FROM words_import"
            f" ON CONFLICT (word) DO UPDATE SET {updates} WHERE {changed}"
        )
    )
    return int(getattr(result, "rowcount", 0))


async def download(
    url: str,
    dest: Path,
    sha256: str = SHA256,
    *,
    transport: httpx2.AsyncBaseTransport | None = None,
) -> Path:
    """Fetch the CSV to `dest` unless a matching copy is already there."""
    if await asyncio.to_thread(_matches, dest, sha256):
        return dest
    target = anyio.Path(dest)
    await target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(".part")
    digest = hashlib.sha256()
    print(f"downloading {url}", file=sys.stderr)
    async with httpx2.AsyncClient(follow_redirects=True, timeout=60, transport=transport) as client:
        async with client.stream("GET", url) as response:
            if response.status_code != 200:
                raise DownloadError(f"HTTP {response.status_code} from {url}")
            async with await partial.open("wb") as f:
                async for chunk in response.aiter_bytes():
                    digest.update(chunk)
                    await f.write(chunk)
    if digest.hexdigest() != sha256:
        await partial.unlink()
        raise DownloadError(f"{url} is not the pinned ECDICT file (sha256 mismatch)")
    await partial.replace(target)
    return dest


def _matches(path: Path, sha256: str) -> bool:
    return path.exists() and _sha256(path) == sha256


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


async def import_csv(database_url: str, path: Path) -> tuple[Stats, int]:
    stats = Stats()
    engine = create_engine(database_url)
    try:
        async with engine.begin() as conn:
            with path.open(newline="", encoding="utf-8") as f:
                changed = await load_words(conn, read_subset(f, stats))
    finally:
        await engine.dispose()
    return stats, changed


async def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--csv", type=Path, help="import this local ecdict.csv, no download")
    args = parser.parse_args(argv)
    settings = get_settings()
    started = time.monotonic()
    try:
        path = args.csv or await download(settings.ecdict_url or DEFAULT_URL, CACHE_PATH)
    except (DownloadError, httpx2.HTTPError) as exc:
        print(f"download failed: {exc}", file=sys.stderr)
        print("set ECDICT_URL to a mirror, or pass --csv with a local copy", file=sys.stderr)
        return 1
    stats, changed = await import_csv(settings.database_url, path)
    print(
        f"read {stats.read} entries, kept {stats.kept}, inserted or updated {changed}"
        f" in {time.monotonic() - started:.1f}s"
    )
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
