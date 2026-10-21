"""Loading Simple English Wiktionary senses into `word_senses` (ADR 0062)."""

import bz2
from datetime import UTC, datetime
from pathlib import Path

import httpx2
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Word, WordSense
from app.services.vocab import import_simplewiktionary
from app.services.vocab.import_simplewiktionary import DownloadError, download, import_file
from tests.conftest import TEST_DATABASE_URL


def page(title: str, text: str) -> str:
    return f"<page><title>{title}</title><ns>0</ns><revision><text>{text}</text></revision></page>"


def write_dump(path: Path, *pages: str) -> Path:
    body = '<mediawiki xmlns="http://www.mediawiki.org/xml/export-0.11/">' + "".join(pages)
    path.write_bytes(bz2.compress((body + "</mediawiki>").encode()))
    return path


async def test_import_replaces_the_senses_and_reports_coverage(
    db_session: AsyncSession, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_session.add_all(
        [
            Word(word="go", translation="v. 去", tags=["zk"]),
            Word(word="school", translation="n. 学校", tags=["zk"]),
            Word(word="rare", translation="a. 稀有的", tags=["gre"]),
        ]
    )
    await db_session.commit()
    monkeypatch.setattr(import_simplewiktionary, "MAX_SENSES", 2)
    monkeypatch.setattr(import_simplewiktionary, "MAX_EXAMPLES", 1)
    go = """== Verb ==
# {{intransitive}} If you go, you move. {{syn|leave}}
#: ''I '''go''' to school.''
#: ''We go home.''
# To work.
# To fit.
"""
    dump = write_dump(
        tmp_path / "dump.xml.bz2",
        page("go", go),
        page("school", "== Noun ==\n# A place to learn."),
        page("Go", "== Proper noun ==\n# A board game."),  # not the word "go"
        page("went", "== Verb ==\n# {{past tense of|go}}"),
    )
    count, books = await import_file(TEST_DATABASE_URL, dump)
    assert count == 3

    go_id = await db_session.scalar(select(Word.id).where(Word.word == "go"))
    rows = (
        await db_session.scalars(
            select(WordSense).where(WordSense.word_id == go_id).order_by(WordSense.rank)
        )
    ).all()
    assert [(r.rank, r.pos, r.gloss) for r in rows] == [
        (0, "verb", "If you go, you move."),
        (1, "verb", "To work."),
    ]
    assert (rows[0].labels, rows[0].examples, rows[0].synonyms) == (
        ["intransitive"],
        ["I go to school."],
        ["leave"],
    )
    assert {(r.source, r.source_title) for r in rows} == {("simplewiktionary", "go")}
    coverage = {book.id: (total, senses, examples) for book, total, senses, examples in books}
    assert coverage["zk"] == (2, 2, 1) and coverage["gre"] == (1, 0, 0)

    # A new dump replaces the old senses instead of adding to them.
    dump = write_dump(tmp_path / "dump.xml.bz2", page("rare", "== Adjective ==\n# Not common."))
    count, _ = await import_file(TEST_DATABASE_URL, dump)
    assert count == 1
    left = (await db_session.scalars(select(WordSense.gloss))).all()
    assert left == ["Not common."]


async def test_download_skips_a_file_already_there_and_dates_it(tmp_path: Path) -> None:
    requests: list[str] = []

    def serve(request: httpx2.Request) -> httpx2.Response:
        requests.append(request.url.path)
        return httpx2.Response(
            200, content=b"x", headers={"last-modified": "Thu, 01 Oct 2026 21:17:45 GMT"}
        )

    transport = httpx2.MockTransport(serve)
    url = "https://mirror.test/dumps/simple.xml.bz2"
    path = await download(tmp_path, url, transport=transport)
    assert path == tmp_path / "simple.xml.bz2" and requests == ["/dumps/simple.xml.bz2"]
    assert datetime.fromtimestamp(path.stat().st_mtime, UTC) == datetime(
        2026, 10, 1, 21, 17, 45, tzinfo=UTC
    )
    await download(tmp_path, url, transport=transport)
    assert len(requests) == 1
    await download(tmp_path, url, refresh=True, transport=transport)
    assert len(requests) == 2

    missing = httpx2.MockTransport(lambda _: httpx2.Response(404))
    with pytest.raises(DownloadError, match="HTTP 404"):
        await download(tmp_path / "new", url, transport=missing)
    assert not list((tmp_path / "new").glob("*.part"))
