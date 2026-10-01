"""Loading Tatoeba sentences into `word_sentences` (ADR 0020): replace, never append."""

import bz2
from datetime import UTC, datetime
from pathlib import Path

import httpx2
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.db.models import Word, WordSentence
from app.services.vocab.import_tatoeba import (
    CMN,
    ENG,
    LINKS,
    DownloadError,
    download,
    import_dir,
)
from tests.conftest import TEST_DATABASE_URL


def write_exports(directory: Path, eng: str, cmn: str, links: str) -> None:
    for name, body in ((ENG, eng), (CMN, cmn), (LINKS, links)):
        (directory / Path(name).name).write_bytes(bz2.compress(body.encode()))


def simplify(text: str) -> str:
    return text.replace("們", "们")


async def test_import_replaces_the_sentences_and_reports_coverage(
    db_engine: AsyncEngine, db_session: AsyncSession, tmp_path: Path
) -> None:
    db_session.add_all(
        [
            Word(word="go", translation="v. 去", exchange="p:went", frq=30, tags=["zk"]),
            Word(word="school", translation="n. 学校", frq=400, tags=["zk"]),
            Word(word="rare", translation="a. 稀有的", frq=9000, tags=["gre"]),
        ]
    )
    await db_session.commit()
    write_exports(
        tmp_path,
        eng="1\teng\tI went to school today.\n2\teng\tGo to school now, please.\n"
        "3\teng\tNo translation here at all.\n",
        cmn="10\tcmn\t我今天去了学校。\n11\tcmn\t我們現在去學校吧。\n",
        links="10\t1\n11\t2\n",
    )
    count, books = await import_dir(TEST_DATABASE_URL, tmp_path, simplify)
    assert count == 4  # go and school each get both; equally good, so by id

    go = await db_session.scalar(select(Word.id).where(Word.word == "go"))
    rows = (
        await db_session.scalars(
            select(WordSentence).where(WordSentence.word_id == go).order_by(WordSentence.rank)
        )
    ).all()
    assert [(r.rank, r.source, r.source_id) for r in rows] == [
        (0, "tatoeba", "1"),
        (1, "tatoeba", "2"),
    ]
    assert rows[1].zh == "我们現在去學校吧。"  # converted by the simplifier given
    coverage = {book.id: (total, covered) for book, total, covered in books}
    assert coverage["zk"] == (2, 2) and coverage["gre"] == (1, 0)

    # A new export replaces the old sentences instead of adding to them.
    write_exports(
        tmp_path,
        eng="5\teng\tWe go to school by bus.\n",
        cmn="50\tcmn\t我们坐公交车上学。\n",
        links="50\t5\n",
    )
    count, _ = await import_dir(TEST_DATABASE_URL, tmp_path, simplify)
    assert count == 2
    left = (await db_session.scalars(select(WordSentence.source_id))).all()
    assert sorted(left) == ["5", "5"]


async def test_download_skips_files_already_there_and_dates_them(tmp_path: Path) -> None:
    requests: list[str] = []

    def serve(request: httpx2.Request) -> httpx2.Response:
        requests.append(request.url.path)
        return httpx2.Response(
            200, content=b"x", headers={"last-modified": "Sat, 26 Sep 2026 06:31:06 GMT"}
        )

    transport = httpx2.MockTransport(serve)
    await download(tmp_path, "https://mirror.test/", transport=transport)
    assert requests == ["/" + ENG, "/" + CMN, "/" + LINKS]
    eng = tmp_path / Path(ENG).name
    assert datetime.fromtimestamp(eng.stat().st_mtime, UTC) == datetime(
        2026, 9, 26, 6, 31, 6, tzinfo=UTC
    )

    await download(tmp_path, "https://mirror.test/", transport=transport)
    assert len(requests) == 3
    await download(tmp_path, "https://mirror.test/", refresh=True, transport=transport)
    assert len(requests) == 6

    missing = httpx2.MockTransport(lambda _: httpx2.Response(404))
    with pytest.raises(DownloadError, match="HTTP 404"):
        await download(tmp_path / "new", "https://mirror.test/", transport=missing)
    assert not list((tmp_path / "new").glob("*.part"))
