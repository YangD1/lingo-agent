"""Import example sentences from Tatoeba into `word_sentences`:
`python -m app.services.vocab.import_tatoeba`.

ADR 0020: Tatoeba's English sentences with a Mandarin translation (CC BY 2.0 FR),
up to two per word, picked for few uncommon words and a moderate length. Traditional
Chinese is converted to simplified. The exports change weekly and have no versioned
address, so nothing is pinned: each file's date and sha256 are printed instead, and
`--dir` imports local copies. Downloads are cached in `data/tatoeba/` (gitignored);
`--refresh` fetches them again. A run replaces all Tatoeba rows in one transaction.
Runs on the host (`make sentences-import`), like the ECDICT import.
"""

import argparse
import asyncio
import bz2
import hashlib
import os
import re
import sys
import time
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

import anyio
import httpx2
from sqlalchemy import delete, exists, func, select
from sqlalchemy.ext.asyncio import AsyncConnection

from app.db.models import Word, WordSentence
from app.db.session import create_engine
from app.services.vocab.books import BOOKS, Book
from app.services.vocab.examples import forms_of
from app.settings import REPO_ROOT, get_settings

SOURCE = "tatoeba"
BASE_URL = "https://downloads.tatoeba.org/exports/per_language/"
ENG, CMN, LINKS = (
    "eng/eng_sentences.tsv.bz2",
    "cmn/cmn_sentences.tsv.bz2",
    "cmn/cmn-eng_links.tsv.bz2",
)
CACHE_DIR = REPO_ROOT / "data" / "tatoeba"

PER_WORD = 2
MIN_WORDS, MAX_WORDS = 4, 20
# Sentences this long read best on a card; the further off, the lower they rank.
IDEAL_WORDS = 9
# Words ranked this high (BNC or contemporary frequency) don't count as uncommon.
COMMON_RANK = 5000
# The longest phrase ("a great deal of") matched, in words.
MAX_PHRASE = 4

_TOKEN = re.compile(r"[A-Za-z]+(?:['\u2019-][A-Za-z]+)*")


class DownloadError(Exception):
    """A Tatoeba export could not be fetched."""


@dataclass(frozen=True, slots=True)
class Pair:
    """An English sentence (its Tatoeba id) and a simplified Chinese translation."""

    id: int
    en: str
    zh: str


@dataclass(frozen=True, slots=True)
class Entry:
    """What the picker needs of a `words` row."""

    id: int
    word: str
    exchange: str | None
    rank: int | None


@dataclass
class Vocab:
    """Word forms to word ids. Words spelt in lowercase match any case; words with
    capitals ("English", "US") match only that spelling, so "us" is not "US"."""

    lower: dict[tuple[str, ...], set[int]] = field(default_factory=dict)
    cased: dict[str, set[int]] = field(default_factory=dict)
    common: set[str] = field(default_factory=set)

    @classmethod
    def of(cls, entries: Iterable[Entry]) -> "Vocab":
        vocab = cls()
        for e in entries:
            if e.rank is not None and e.rank <= COMMON_RANK:
                vocab.common |= forms_of(e.word, e.exchange)
            if e.word != e.word.lower():
                if _TOKEN.fullmatch(e.word):
                    vocab.cased.setdefault(e.word, set()).add(e.id)
                continue
            for form in forms_of(e.word, e.exchange, lemma=False):
                gram = tuple(_TOKEN.findall(form))
                # "a.m." is not the words "a" and "m".
                if 0 < len(gram) <= MAX_PHRASE and " ".join(gram) == form:
                    vocab.lower.setdefault(gram, set()).add(e.id)
        return vocab


def _norm(token: str) -> str:
    return token.replace("\u2019", "'")


def pair_up(
    links: Iterable[tuple[int, int]],
    eng: Mapping[int, str],
    cmn: Mapping[int, str],
    simplify: Callable[[str], str],
) -> list[Pair]:
    """One pair per English sentence. Of several translations, one already in
    simplified Chinese is preferred; otherwise the first is converted."""
    found: dict[int, list[str]] = {}
    for cmn_id, eng_id in sorted(links):
        if eng_id in eng and cmn_id in cmn:
            found.setdefault(eng_id, []).append(cmn[cmn_id])
    pairs = []
    for eng_id, translations in sorted(found.items()):
        simplified = [simplify(t) for t in translations]
        same = [s for s, t in zip(simplified, translations, strict=True) if s == t]
        pairs.append(Pair(eng_id, eng[eng_id].strip(), (same or simplified)[0].strip()))
    return pairs


Key = tuple[int, int, int]


def _wording(sentence: str) -> list[str]:
    return [_norm(t).lower() for t in _TOKEN.findall(sentence)]


def _same(a: list[str], b: list[str]) -> bool:
    """The same sentence but for one word ("an example to / for your children")."""
    return len(a) == len(b) and sum(x != y for x, y in zip(a, b, strict=True)) <= 1


def _offer(kept: list[tuple[Key, Pair]], key: Key, pair: Pair) -> None:
    """Keep the best PER_WORD sentences, no two of them the same but for one word."""
    wording = _wording(pair.en)
    for i, (other_key, other) in enumerate(kept):
        if _same(_wording(other.en), wording):
            if key < other_key:
                kept[i] = (key, pair)
                kept.sort(key=lambda kp: kp[0])
            return
    kept.append((key, pair))
    kept.sort(key=lambda kp: kp[0])
    del kept[PER_WORD:]


def pick(pairs: Iterable[Pair], vocab: Vocab) -> dict[int, list[Pair]]:
    """Each word's best sentences, best first: fewest uncommon words besides the word
    itself, then closest to IDEAL_WORDS long, then lowest id (stable across runs).

    A capitalised word inside a sentence is a name ("Tom", "China") unless it is a
    capitalised dictionary word: it neither matches a word nor counts as uncommon.
    """
    best: dict[int, list[tuple[Key, Pair]]] = {}
    for pair in pairs:
        tokens = [_norm(t) for t in _TOKEN.findall(pair.en)]
        if not MIN_WORDS <= len(tokens) <= MAX_WORDS:
            continue
        matched: dict[int, set[str]] = {}
        names: set[int] = set()
        for i, token in enumerate(tokens):
            if token in vocab.cased:
                for word_id in vocab.cased[token]:
                    matched.setdefault(word_id, set()).add(token.lower())
            if i > 0 and token[0].isupper() and token != "I":
                names.add(i)
        lowered = [t.lower() for t in tokens]
        for i in range(len(tokens)):
            for size in range(1, MAX_PHRASE + 1):
                span = range(i, i + size)
                if i + size > len(tokens) or names.intersection(span):
                    break
                gram = tuple(lowered[i : i + size])
                for word_id in vocab.lower.get(gram, ()):
                    matched.setdefault(word_id, set()).add(" ".join(gram))
        uncommon = [t for i, t in enumerate(lowered) if i not in names and t not in vocab.common]
        for word_id, forms in matched.items():
            rare = sum(1 for t in uncommon if t not in forms)
            key = (rare, abs(len(tokens) - IDEAL_WORDS), pair.id)
            _offer(best.setdefault(word_id, []), key, pair)
    return {word_id: [p for _, p in kept] for word_id, kept in best.items()}


def _rows(path: Path) -> Iterator[list[str]]:
    """Tab-separated rows of a Tatoeba export, bzip2-compressed or not."""
    opener: Any = bz2.open if path.suffix == ".bz2" else open
    with opener(path, "rt", encoding="utf-8", newline="\n") as f:
        for line in f:
            yield line.rstrip("\n").split("\t")


def _find(directory: Path, name: str) -> Path:
    """The export in `directory`, compressed or already unpacked."""
    path = directory / Path(name).name
    return path if path.exists() else path.with_suffix("")


def read_pairs(directory: Path, simplify: Callable[[str], str]) -> list[Pair]:
    links = [(int(c), int(e)) for c, e, *_ in _rows(_find(directory, LINKS))]
    cmn = {int(i): t for i, _, t in _rows(_find(directory, CMN))}
    wanted = {e for _, e in links}
    # 2M English sentences: keep only the translated ones.
    eng = {int(i): t for i, _, t in _rows(_find(directory, ENG)) if int(i) in wanted}
    return pair_up(links, eng, cmn, simplify)


async def read_vocab(conn: AsyncConnection) -> Vocab:
    rows = await conn.execute(select(Word.id, Word.word, Word.exchange, Word.frq, Word.bnc))
    return Vocab.of(
        Entry(id, word, exchange, min((r for r in (frq, bnc) if r is not None), default=None))
        for id, word, exchange, frq, bnc in rows
    )


async def load_sentences(conn: AsyncConnection, picked: Mapping[int, list[Pair]]) -> int:
    """Replace all Tatoeba rows with `picked`; does not commit. Returns the row count."""
    await conn.execute(delete(WordSentence).where(WordSentence.source == SOURCE))
    raw: Any = (await conn.get_raw_connection()).driver_connection
    count = 0
    columns = "word_id, source, rank, en, zh, source_id"
    async with raw.cursor() as cursor:
        async with cursor.copy(f"COPY word_sentences ({columns}) FROM STDIN") as copy:
            for word_id, pairs in sorted(picked.items()):
                for rank, p in enumerate(pairs):
                    await copy.write_row((word_id, SOURCE, rank, p.en, p.zh, str(p.id)))
                    count += 1
    return count


async def coverage(conn: AsyncConnection) -> list[tuple[Book, int, int]]:
    """Per book: how many words, and how many have a sentence."""
    has_one = exists().where(WordSentence.word_id == Word.id)
    result = []
    for book in BOOKS:
        row = (
            await conn.execute(
                select(func.count(), func.count().filter(has_one)).where(book.words())
            )
        ).one()
        result.append((book, int(row[0]), int(row[1])))
    return result


async def download(
    directory: Path,
    base_url: str = BASE_URL,
    *,
    refresh: bool = False,
    transport: httpx2.AsyncBaseTransport | None = None,
) -> Path:
    """Fetch the three exports into `directory` unless they are there already. A
    file's modification time is set to the export's date."""
    async with httpx2.AsyncClient(follow_redirects=True, timeout=60, transport=transport) as client:
        for name in (ENG, CMN, LINKS):
            target = anyio.Path(directory / Path(name).name)
            if await target.exists() and not refresh:
                continue
            await target.parent.mkdir(parents=True, exist_ok=True)
            partial = target.with_suffix(".part")
            url = base_url + name
            print(f"downloading {url}", file=sys.stderr)
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
    return directory


def describe(directory: Path) -> list[str]:
    """Each export's date and sha256, to record which version was imported."""
    lines = []
    for name in (ENG, CMN, LINKS):
        path = _find(directory, name)
        digest = hashlib.sha256()
        with path.open("rb") as f:
            while chunk := f.read(1 << 20):
                digest.update(chunk)
        date = time.strftime("%Y-%m-%d", time.gmtime(path.stat().st_mtime))
        lines.append(f"{path.name}  {date}  sha256 {digest.hexdigest()}")
    return lines


def _simplifier() -> Callable[[str], str]:
    from opencc import OpenCC  # only needed here; a dev dependency

    convert: Callable[[str], str] = OpenCC("t2s").convert
    return convert


async def import_dir(
    database_url: str, directory: Path, simplify: Callable[[str], str] | None = None
) -> tuple[int, list[tuple[Book, int, int]]]:
    """Import from the exports in `directory`; returns rows written and coverage."""
    pairs = await asyncio.to_thread(read_pairs, directory, simplify or _simplifier())
    engine = create_engine(database_url)
    try:
        async with engine.begin() as conn:
            picked = pick(pairs, await read_vocab(conn))
            count = await load_sentences(conn, picked)
            books = await coverage(conn)
    finally:
        await engine.dispose()
    return count, books


async def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dir", type=Path, help="import the exports in this directory")
    parser.add_argument("--refresh", action="store_true", help="download the exports again")
    args = parser.parse_args(argv)
    started = time.monotonic()
    try:
        directory = args.dir or await download(CACHE_DIR, refresh=args.refresh)
    except (DownloadError, httpx2.HTTPError) as exc:
        print(f"download failed: {exc}", file=sys.stderr)
        print("pass --dir with local copies of the Tatoeba exports", file=sys.stderr)
        return 1
    for line in await asyncio.to_thread(describe, directory):
        print(line)
    count, books = await import_dir(get_settings().database_url, directory)
    print(f"wrote {count} sentences in {time.monotonic() - started:.1f}s")
    for book, total, covered in books:
        share = covered / total if total else 0
        print(f"  {book.id:<11} {covered:>5} / {total:<5} words have a sentence ({share:.0%})")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
